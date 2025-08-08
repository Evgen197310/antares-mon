from flask import Blueprint, render_template, request, jsonify, current_app, send_from_directory
from app.models.database import db_manager
from datetime import datetime, timedelta
import logging
import csv
import os
import ipaddress

bp = Blueprint('vpn', __name__)

def read_mikrotik_map():
    """Чтение карты MikroTik роутеров"""
    try:
        map_file = current_app.config.get('MIKROTIK_MAP_FILE', '/opt/ike2web/data/full_map.csv')
        if not os.path.exists(map_file):
            return []
        
        routers = []
        with open(map_file, 'r', encoding='utf-8') as f:
            peek = f.readline()
            f.seek(0)
            header_like = any(k in peek.lower() for k in ['identity', 'ip', 'location', 'type'])
            if header_like:
                reader = csv.DictReader(f)
                for row in reader:
                    routers.append({
                        'identity': row.get('identity', ''),
                        'ip': row.get('ip', ''),
                        'location': row.get('location', ''),
                        'type': row.get('type', '')
                    })
            else:
                reader = csv.reader(f)
                for row in reader:
                    if not row:
                        continue
                    identity = row[0].strip() if len(row) > 0 else ''
                    ip = row[1].strip() if len(row) > 1 else ''
                    # Встречаются файлы вида: identity, ip, prefix, tunnel, code
                    location = row[3].strip() if len(row) > 3 else 'Unknown'
                    typecode = row[4].strip() if len(row) > 4 else ''
                    rtype = {'D': 'Dynamic', 'I': 'Internal'}.get(typecode, typecode or '-')
                    routers.append({
                        'identity': identity,
                        'ip': ip,
                        'location': location or 'Unknown',
                        'type': rtype,
                    })
        return routers
    except Exception as e:
        current_app.logger.error(f"Error reading MikroTik map: {e}")
        return []

def _parse_login_time(ts: str):
    """Парсим строку времени в datetime, совместимо с Python 3.6.
    Поддерживаем варианты: 'YYYY-MM-DDTHH:MM:SS.%f', 'YYYY-MM-DDTHH:MM:SS',
    'YYYY-MM-DD HH:MM:SS.%f', 'YYYY-MM-DD HH:MM:SS'.
    """
    if not ts:
        return None
    s = ts.strip()
    # Варианты с 'T'
    if 'T' in s:
        s2 = s.replace('T', ' ')
        for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
            try:
                return datetime.strptime(s2, fmt)
            except Exception:
                pass
    # Варианты без 'T'
    for fmt in ('%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None

def _format_duration_from(dt: datetime):
    """Человекочитаемая длительность с момента dt до сейчас (ru)."""
    if not dt:
        return 'N/A'
    try:
        delta = datetime.now() - dt
        total = int(delta.total_seconds())
        if total < 0:
            total = 0
        hours = total // 3600
        minutes = (total % 3600) // 60
        if hours > 0:
            return f"{hours} ч {minutes} м"
        return f"{minutes} м"
    except Exception:
        return 'N/A'

def read_active_vpn_sessions():
    """Чтение активных VPN сессий из файла состояния.
    Поддерживает CSV без заголовка (username,outer_ip,inner_ip,time_start[,router]).
    """
    try:
        state_file = current_app.config.get('VPN_STATE_FILE', '/var/log/mikrotik/ikev2_active.csv')
        if not os.path.exists(state_file):
            return []

        sessions = []
        with open(state_file, 'r', encoding='utf-8') as f:
            peek = f.readline()
            f.seek(0)
            # Определяем есть ли заголовок по наличию буквенных ключей
            header_like = any(k in peek.lower() for k in ['username', 'outer', 'inner', 'time'])
            if header_like:
                reader = csv.DictReader(f)
                for row in reader:
                    sessions.append({
                        'username': row.get('username', '') or row.get('user', ''),
                        'outer_ip': row.get('outer_ip', '') or row.get('remote_address', ''),
                        'inner_ip': row.get('inner_ip', ''),
                        'time_start': row.get('time_start', '') or row.get('login_time', ''),
                        'router': row.get('router', '') or row.get('device_name', '')
                    })
            else:
                reader = csv.reader(f)
                for row in reader:
                    if not row:
                        continue
                    # Ожидаем минимум 4 колонки
                    username = row[0].strip() if len(row) > 0 else ''
                    outer_ip = row[1].strip() if len(row) > 1 else ''
                    inner_ip = row[2].strip() if len(row) > 2 else ''
                    time_start = row[3].strip() if len(row) > 3 else ''
                    router = row[4].strip() if len(row) > 4 else ''
                    sessions.append({
                        'username': username,
                        'outer_ip': outer_ip,
                        'inner_ip': inner_ip,
                        'time_start': time_start,
                        'router': router,
                    })
        return sessions
    except Exception as e:
        current_app.logger.error(f"Error reading VPN state: {e}")
        return []

@bp.route('/')
def index():
    """Главная страница VPN мониторинга"""
    try:
        # Получаем активные сессии из CSV файла (единый источник)
        raw_sessions = read_active_vpn_sessions()
        # Приводим к полям, ожидаемым шаблоном: username, remote_address, inner_ip, device_name, login_time, duration
        sessions = []
        for s in raw_sessions:
            # Конвертация времени и расчёт длительности
            ts = s.get('time_start')
            login_dt = _parse_login_time(ts)
            sessions.append({
                'username': s.get('username') or '',
                'remote_address': s.get('outer_ip') or '',
                'inner_ip': s.get('inner_ip') or '',
                'device_name': s.get('router') or '',
                'login_time': login_dt,
                'login_iso': login_dt.isoformat() if login_dt else '',
                'duration': _format_duration_from(login_dt),
            })
        
        # Получаем статистику из базы данных
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cursor:
                # Статистика за сегодня
                cursor.execute("""
                    SELECT COUNT(*) as today_sessions,
                           COUNT(DISTINCT username) as unique_users
                    FROM session_history 
                    WHERE DATE(time_start) = CURDATE()
                """)
                today_stats = cursor.fetchone()
                
                # Статистика за неделю
                cursor.execute("""
                    SELECT COUNT(*) as week_sessions,
                           COUNT(DISTINCT username) as unique_users
                    FROM session_history 
                    WHERE time_start >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                """)
                week_stats = cursor.fetchone()

        # Дополнительные метрики для карточек
        mikrotik_devices = len(read_mikrotik_map())
        stats = {
            'active_sessions': len(sessions),
            'today_sessions': (today_stats or {}).get('today_sessions', 0) if isinstance(today_stats, dict) else (today_stats['today_sessions'] if today_stats else 0),
            'mikrotik_devices': mikrotik_devices,
            'avg_duration': '0m',  # при необходимости вычислим позже
        }

        return render_template('vpn/index.html',
                             sessions=sessions,
                             stats=stats,
                             today_stats=today_stats,
                             week_stats=week_stats,
                             server_now=datetime.now().isoformat())
    except Exception as e:
        current_app.logger.error(f"VPN index error: {e}")
        return render_template('vpn/index.html', 
                             sessions=[], 
                             stats={'active_sessions': 0, 'today_sessions': 0, 'mikrotik_devices': 0, 'avg_duration': '0m'},
                             today_stats={},
                             week_stats={})

@bp.route('/topology')
def topology():
    """Топология MikroTik роутеров"""
    try:
        routers = read_mikrotik_map()
        return render_template('vpn/topology.html', routers=routers)
    except Exception as e:
        current_app.logger.error(f"VPN topology error: {e}")
        return render_template('vpn/topology.html', routers=[])

@bp.route('/history')
def history():
    """История VPN сессий"""
    try:
        page = request.args.get('page', 1, type=int)
        username = request.args.get('username', '').strip()
        days = request.args.get('days', 7, type=int)
        per_page = 50
        offset = (page - 1) * per_page
        
        # Ограничиваем период
        date_from = datetime.now() - timedelta(days=days)
        
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cursor:
                # Строим запрос с фильтрами
                where_conditions = ["time_start >= %s"]
                params = [date_from]
                
                if username:
                    where_conditions.append("username LIKE %s")
                    params.append(f"%{username}%")
                
                where_clause = " AND ".join(where_conditions)
                
                # Получаем общее количество записей
                cursor.execute(f"""
                    SELECT COUNT(*) as total 
                    FROM session_history 
                    WHERE {where_clause}
                """, params)
                total = cursor.fetchone()['total']
                
                # Получаем записи для текущей страницы
                cursor.execute(f"""
                    SELECT username, outer_ip, inner_ip, time_start, time_end, duration
                    FROM session_history 
                    WHERE {where_clause}
                    ORDER BY time_start DESC
                    LIMIT %s OFFSET %s
                """, params + [per_page, offset])
                
                sessions = cursor.fetchall()
                
                # Пагинация
                has_prev = page > 1
                has_next = offset + per_page < total
                prev_num = page - 1 if has_prev else None
                next_num = page + 1 if has_next else None
                
                return render_template('vpn/history.html',
                                     sessions=sessions,
                                     username=username,
                                     days=days,
                                     page=page,
                                     per_page=per_page,
                                     total=total,
                                     has_prev=has_prev,
                                     has_next=has_next,
                                     prev_num=prev_num,
                                     next_num=next_num)
    except Exception as e:
        current_app.logger.error(f"VPN history error: {e}")
        return render_template('vpn/history.html', sessions=[])

@bp.route('/user/<username>')
def user_detail(username):
    """Детальная страница пользователя VPN"""
    try:
        page = request.args.get('page', 1, type=int)
        days = request.args.get('days', 30, type=int)
        per_page = 50
        offset = (page - 1) * per_page
        
        # Ограничиваем период: 0 = все время
        date_from = None if days == 0 else (datetime.now() - timedelta(days=days))
        
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cursor:
                # Получаем общее количество записей пользователя
                if date_from is None:
                    cursor.execute("""
                        SELECT COUNT(*) as total 
                        FROM session_history 
                        WHERE username = %s
                    """, (username,))
                else:
                    cursor.execute("""
                        SELECT COUNT(*) as total 
                        FROM session_history 
                        WHERE username = %s AND time_start >= %s
                    """, (username, date_from))
                total = cursor.fetchone()['total']
                
                # Получаем записи для текущей страницы
                if date_from is None:
                    cursor.execute("""
                        SELECT username, outer_ip, inner_ip, time_start, time_end, duration
                        FROM session_history 
                        WHERE username = %s
                        ORDER BY time_start DESC
                        LIMIT %s OFFSET %s
                    """, (username, per_page, offset))
                else:
                    cursor.execute("""
                        SELECT username, outer_ip, inner_ip, time_start, time_end, duration
                        FROM session_history 
                        WHERE username = %s AND time_start >= %s
                        ORDER BY time_start DESC
                        LIMIT %s OFFSET %s
                    """, (username, date_from, per_page, offset))
                
                sessions = cursor.fetchall()
                
                # Статистика пользователя
                if date_from is None:
                    cursor.execute("""
                        SELECT 
                            COUNT(*) as total_sessions,
                            COUNT(CASE WHEN time_end IS NULL THEN 1 END) as active_sessions,
                            AVG(duration) as avg_duration,
                            SUM(duration) as total_duration,
                            COUNT(DISTINCT DATE(time_start)) as active_days,
                            MIN(time_start) as first_session,
                            MAX(time_start) as last_session
                        FROM session_history 
                        WHERE username = %s
                    """, (username,))
                else:
                    cursor.execute("""
                        SELECT 
                            COUNT(*) as total_sessions,
                            COUNT(CASE WHEN time_end IS NULL THEN 1 END) as active_sessions,
                            AVG(duration) as avg_duration,
                            SUM(duration) as total_duration,
                            COUNT(DISTINCT DATE(time_start)) as active_days,
                            MIN(time_start) as first_session,
                            MAX(time_start) as last_session
                        FROM session_history 
                        WHERE username = %s AND time_start >= %s
                    """, (username, date_from))
                stats = cursor.fetchone()
                
                # Пагинация
                has_prev = page > 1
                has_next = offset + per_page < total
                prev_num = page - 1 if has_prev else None
                next_num = page + 1 if has_next else None
                
                return render_template('vpn/user_detail.html',
                                     username=username,
                                     sessions=sessions,
                                     stats=stats,
                                     days=days,
                                     page=page,
                                     per_page=per_page,
                                     total=total,
                                     has_prev=has_prev,
                                     has_next=has_next,
                                     prev_num=prev_num,
                                     next_num=next_num,
                                     server_now=datetime.now().isoformat())
    except Exception as e:
        current_app.logger.error(f"VPN user detail error: {e}")
        return render_template('vpn/user_detail.html', 
                             username=username, 
                             sessions=[], 
                             stats={})

@bp.route('/map')
def mikrotik_map():
    """Карта MikroTik роутеров"""
    try:
        routers = read_mikrotik_map()
        
        # Группируем роутеры по типам/локациям
        grouped_routers = {}
        for router in routers:
            location = router.get('location', 'Unknown')
            if location not in grouped_routers:
                grouped_routers[location] = []
            grouped_routers[location].append(router)
        
        return render_template('vpn/map.html', 
                             routers=routers,
                             grouped_routers=grouped_routers)
    except Exception as e:
        current_app.logger.error(f"VPN map error: {e}")
        return render_template('vpn/map.html', routers=[], grouped_routers={})

@bp.route('/mikrotik_topology')
def mikrotik_topology():
    """Визуальная топология MikroTik, как в исходном проекте.
    Формирует узлы и ребра на основе CSV карты (FULL_MAP_FILE).
    """
    try:
        # Путь к полному дампу адресов/интерфейсов
        full_map = current_app.config.get('FULL_MAP_FILE', current_app.config.get('MIKROTIK_MAP_FILE', '/opt/ike2web/data/full_map.csv'))
        if not os.path.exists(full_map):
            current_app.logger.warning(f"FULL_MAP_FILE not found: {full_map}")
            return render_template('vpn/mikrotik_topology.html', nodes=[], edges=[])

        # какие L2TP-префиксы считаем активными (как в оригинале)
        L2TP_PREFIXES = ("192.168.90.", "10.10.20.")

        def is_l2tp_ip(ip: str) -> bool:
            return any(ip.startswith(p) for p in L2TP_PREFIXES)

        def subnet_key(ip: str) -> str:
            return ".".join(ip.split(".")[:3])

        routers = {}
        l2tp_peers = []
        with open(full_map, encoding='utf-8') as f:
            for row in csv.reader(f):
                if len(row) < 4:
                    continue
                identity, ip, mask, iface = [x.strip() for x in row[:4]]
                flag = row[4].strip() if len(row) > 4 else ""
                if flag == "I":  # пропускаем внутренние
                    continue
                r = routers.setdefault(identity, {'lans': [], 'l2tps': []})
                if iface.startswith(('bridge', 'ether', 'vlan')):
                    r['lans'].append(f"{ip}/{mask}")
                if iface.lower().startswith('l2tp') or is_l2tp_ip(ip):
                    r['l2tps'].append(f"{ip}/{mask}")
                    l2tp_peers.append((identity, ip))

        l2tp_subnets = {}
        for identity, ip in l2tp_peers:
            key = subnet_key(ip)
            entry = l2tp_subnets.setdefault(key, {'server': None, 'clients': []})
            if ip.endswith('.1'):
                entry['server'] = (identity, ip)
            else:
                entry['clients'].append((identity, ip))

        nodes = []
        for identity, info in routers.items():
            label = f"<b>{identity}</b>"
            if info['lans']:
                label += "\nLAN: " + ", ".join(info['lans'])
            if info['l2tps']:
                label += "\nL2TP: " + ", ".join(info['l2tps'])
            nodes.append({"id": identity, "label": label, "shape": "box", "color": "#AED6F1"})

        edges = []
        for key, entry in l2tp_subnets.items():
            if not entry['server']:
                continue
            srv_id, srv_ip = entry['server']
            for cli_id, cli_ip in entry['clients']:
                if cli_id == srv_id:
                    continue
                edges.append({
                    "from": cli_id,
                    "to":   srv_id,
                    "label": f"{key}.x  ({cli_ip}\u2192{srv_ip})",
                    "arrows": {"to": {"enabled": True, "scaleFactor": 1.3}},
                    "color": "#2874A6",
                    "width": 2
                })

        return render_template("vpn/mikrotik_topology.html", nodes=nodes, edges=edges)
    except Exception as e:
        current_app.logger.error(f"VPN mikrotik_topology error: {e}")
        return render_template("vpn/mikrotik_topology.html", nodes=[], edges=[])

@bp.route('/stats')
def stats():
    """Статистика VPN"""
    try:
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cursor:
                # Активные сессии
                cursor.execute("SELECT COUNT(*) as active FROM session_history WHERE time_end IS NULL")
                active_sessions = cursor.fetchone()['active']
                
                # Статистика по дням за последние 30 дней
                cursor.execute("""
                    SELECT DATE(time_start) as date, 
                           COUNT(*) as sessions,
                           COUNT(DISTINCT username) as users
                    FROM session_history 
                    WHERE time_start >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                    GROUP BY DATE(time_start)
                    ORDER BY date DESC
                """)
                daily_stats = cursor.fetchall()
                
                # Топ пользователи за последние 30 дней
                cursor.execute("""
                    SELECT username, 
                           COUNT(*) as sessions,
                           AVG(duration) as avg_duration,
                           SUM(duration) as total_duration
                    FROM session_history 
                    WHERE time_start >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                    GROUP BY username
                    ORDER BY sessions DESC
                    LIMIT 20
                """)
                top_users = cursor.fetchall()
                
                # Статистика по часам
                cursor.execute("""
                    SELECT HOUR(time_start) as hour,
                           COUNT(*) as sessions
                    FROM session_history 
                    WHERE time_start >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                    GROUP BY HOUR(time_start)
                    ORDER BY hour
                """)
                hourly_stats = cursor.fetchall()
                
                return render_template('vpn/stats.html',
                                     active_sessions=active_sessions,
                                     daily_stats=daily_stats,
                                     top_users=top_users,
                                     hourly_stats=hourly_stats)
    except Exception as e:
        current_app.logger.error(f"VPN stats error: {e}")
        return render_template('vpn/stats.html', 
                             active_sessions=0,
                             daily_stats=[],
                             top_users=[],
                             hourly_stats=[])

# API endpoints для VPN
@bp.route('/api/sessions')
def api_sessions():
    """API: Получить активные VPN сессии"""
    try:
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT username, outer_ip, inner_ip, time_start,
                           TIMESTAMPDIFF(SECOND, time_start, NOW()) as duration_seconds
                    FROM session_history 
                    WHERE time_end IS NULL 
                    ORDER BY time_start DESC
                """)
                sessions = cursor.fetchall()
                
                # Преобразуем datetime в строки для JSON
                for session in sessions:
                    if session.get('time_start'):
                        session['time_start'] = session['time_start'].isoformat()
                
                return jsonify({
                    "status": "success",
                    "count": len(sessions),
                    "data": sessions
                })
    except Exception as e:
        current_app.logger.error(f"VPN API sessions error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/api/stats')
def api_stats():
    """API: Статистика VPN"""
    try:
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cursor:
                # Активные сессии
                cursor.execute("SELECT COUNT(*) as active FROM session_history WHERE time_end IS NULL")
                active_count = cursor.fetchone()['active']
                
                # Всего сессий за сегодня
                cursor.execute("""
                    SELECT COUNT(*) as today 
                    FROM session_history 
                    WHERE DATE(time_start) = CURDATE()
                """)
                today_count = cursor.fetchone()['today']
                
                # Уникальные пользователи за сегодня
                cursor.execute("""
                    SELECT COUNT(DISTINCT username) as unique_users 
                    FROM session_history 
                    WHERE DATE(time_start) = CURDATE()
                """)
                unique_users = cursor.fetchone()['unique_users']
                
                return jsonify({
                    "status": "success",
                    "data": {
                        "active_sessions": active_count,
                        "sessions_today": today_count,
                        "unique_users_today": unique_users,
                        "timestamp": datetime.now().isoformat()
                    }
                })
    except Exception as e:
        current_app.logger.error(f"VPN API stats error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/admin-doc')
def admin_doc():
    """Документация администратора VPN"""
    try:
        doc_file = current_app.config.get('VPN_ADMIN_DOC', '/opt/ike2web/static/vpn_admin_doc.html')
        if os.path.exists(doc_file):
            return send_from_directory(os.path.dirname(doc_file), os.path.basename(doc_file))
        else:
            return render_template('vpn/admin_doc.html')
    except Exception as e:
        current_app.logger.error(f"VPN admin doc error: {e}")
        return "Документация недоступна", 404
