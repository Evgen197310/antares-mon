from flask import Blueprint, render_template, request, jsonify, current_app, send_from_directory, redirect, url_for
from app.models.database import db_manager
from datetime import datetime, timedelta
import logging
import csv
import os
import ipaddress

bp = Blueprint('vpn', __name__)

def read_mikrotik_map():
    """Чтение карты MikroTik: возвращает список адресов на интерфейсах.
    Единица списка — адрес (ip/mask) на интерфейсе устройства.
    Поля: identity, ip, iface, type.
    """
    try:
        map_file = current_app.config.get('MIKROTIK_MAP_FILE', '/opt/ike2web/data/full_map.csv')
        if not os.path.exists(map_file):
            return []

        rows = []
        with open(map_file, 'r', encoding='utf-8') as f:
            peek = f.readline()
            f.seek(0)
            lower = peek.lower()
            header_like = any(k in lower for k in ['identity', 'ip', 'iface', 'interface', 'type', 'mask'])
            if header_like:
                reader = csv.DictReader(f)
                for row in reader:
                    identity = (row.get('identity') or row.get('Identity') or '').strip()
                    ip = (row.get('ip') or row.get('address') or '').strip()
                    iface = (row.get('iface') or row.get('interface') or row.get('location') or '').strip()
                    rtype = (row.get('type') or row.get('flag') or '').strip()
                    if rtype in ('D', 'I'):
                        rtype = {'D': 'Dynamic', 'I': 'Internal'}[rtype]
                    rows.append({'identity': identity, 'ip': ip, 'iface': iface, 'type': rtype})
            else:
                reader = csv.reader(f)
                for row in reader:
                    if not row:
                        continue
                    # Ожидаемый порядок: identity, ip, mask, iface, flag(optional)
                    identity = row[0].strip() if len(row) > 0 else ''
                    ip = row[1].strip() if len(row) > 1 else ''
                    mask = row[2].strip() if len(row) > 2 else ''
                    iface = row[3].strip() if len(row) > 3 else ''
                    flag = row[4].strip() if len(row) > 4 else ''
                    rtype = {'D': 'Dynamic', 'I': 'Internal'}.get(flag, flag or '-')
                    ip_show = f"{ip}/{mask}" if mask else ip
                    rows.append({'identity': identity, 'ip': ip_show, 'iface': iface, 'type': rtype})
        return rows
    except Exception as e:
        current_app.logger.error(f"Error reading MikroTik map: {e}")
        return []

def _build_mikrotik_networks():
    """Строит список (identity, ip_network) из карты MikroTik."""
    nets = []
    try:
        rows = read_mikrotik_map()
        for r in rows:
            cidr = (r.get('ip') or '').strip()
            identity = (r.get('identity') or '').strip()
            if not cidr or '/' not in cidr or not identity:
                continue
            try:
                net = ipaddress.ip_network(cidr, strict=False)
            except Exception:
                continue
            nets.append((identity, net))
    except Exception:
        pass
    return nets

def _resolve_router_by_inner_ip(inner_ip: str):
    """Возвращает identity MikroTik по внутреннему IP подключения."""
    if not inner_ip:
        return ''
    try:
        ip_obj = ipaddress.ip_address(inner_ip)
    except Exception:
        return ''
    for identity, net in _build_mikrotik_networks():
        try:
            if ip_obj in net:
                return identity
        except Exception:
            continue
    return ''

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
        mikrotik_map = read_mikrotik_map()
        # Считаем уникальные устройства по identity (как в топологии)
        unique_devices = len(set(row['identity'] for row in mikrotik_map if row.get('identity')))
        
        # Расчёт средней длительности активных сессий
        avg_duration = '0м'
        if sessions:
            total_minutes = 0
            valid_sessions = 0
            for s in sessions:
                if s.get('login_time'):
                    delta = datetime.now() - s['login_time']
                    minutes = int(delta.total_seconds() / 60)
                    if minutes >= 0:
                        total_minutes += minutes
                        valid_sessions += 1
            if valid_sessions > 0:
                avg_min = total_minutes // valid_sessions
                hours = avg_min // 60
                mins = avg_min % 60
                if hours > 0:
                    avg_duration = f"{hours} ч {mins} м"
                else:
                    avg_duration = f"{mins} м"
        
        stats = {
            'active_sessions': len(sessions),
            'today_sessions': (today_stats or {}).get('today_sessions', 0) if isinstance(today_stats, dict) else (today_stats['today_sessions'] if today_stats else 0),
            'mikrotik_devices': unique_devices,
            'avg_duration': avg_duration,
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
    """Топология сети (визуальный граф): сохраняем как /topology.
    Для совместимости просто перенаправляем на существующий визуальный граф.
    """
    return redirect(url_for('vpn.mikrotik_topology'))

@bp.route('/interfaces')
def interfaces():
    """Список адресов на интерфейсах MikroTik с агрегированными счетчиками."""
    try:
        rows = read_mikrotik_map()
        selected_identity = request.args.get('identity', '').strip()
        if selected_identity:
            rows = [r for r in rows if (r.get('identity') or '').strip() == selected_identity]
        address_count = len(rows)
        device_count = len({r.get('identity') for r in rows if r.get('identity')})
        interface_count = len({(r.get('identity'), r.get('iface')) for r in rows if r.get('identity') and r.get('iface')})
        return render_template('vpn/topology.html', routers=rows, address_count=address_count, device_count=device_count, interface_count=interface_count, selected_identity=selected_identity)
    except Exception as e:
        current_app.logger.error(f"VPN interfaces error: {e}")
        return render_template('vpn/topology.html', routers=[], address_count=0, device_count=0, interface_count=0, selected_identity='')

@bp.route('/history')
def history():
    """История VPN сессий"""
    try:
        page = request.args.get('page', 1, type=int)
        username = request.args.get('username', '').strip()
        outer_ip = request.args.get('outer_ip', '').strip()
        inner_ip = request.args.get('inner_ip', '').strip()
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
                if outer_ip:
                    where_conditions.append("outer_ip = %s")
                    params.append(outer_ip)
                if inner_ip:
                    where_conditions.append("inner_ip = %s")
                    params.append(inner_ip)
                
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
                    SELECT username,
                           outer_ip,
                           inner_ip,
                           time_start,
                           time_end,
                           TIMESTAMPDIFF(SECOND, time_start, COALESCE(time_end, NOW())) AS duration_seconds
                    FROM session_history 
                    WHERE {where_clause}
                    ORDER BY time_start DESC
                    LIMIT %s OFFSET %s
                """, params + [per_page, offset])
                
                sessions = cursor.fetchall()
                # enrich with router identity by inner_ip
                for it in sessions:
                    if not it.get('device_name'):
                        it['device_name'] = _resolve_router_by_inner_ip(it.get('inner_ip')) or '-'
                
                # Пагинация
                has_prev = page > 1
                has_next = offset + per_page < total
                prev_num = page - 1 if has_prev else None
                next_num = page + 1 if has_next else None
                
                return render_template('vpn/history.html',
                                     sessions=sessions,
                                     username=username,
                                     outer_ip=outer_ip,
                                     inner_ip=inner_ip,
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
                cursor.execute(
                    """
                    SELECT DATE(time_start) AS date,
                           COUNT(*) AS sessions,
                           COUNT(DISTINCT username) AS users
                    FROM session_history
                    WHERE time_start >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                    GROUP BY DATE(time_start)
                    ORDER BY date DESC
                    """
                )
                daily_stats = cursor.fetchall()
                
                # Топ пользователи за последние 30 дней
                cursor.execute(
                    """
                    SELECT username,
                           COUNT(*) AS sessions,
                           AVG(TIMESTAMPDIFF(SECOND, time_start, COALESCE(time_end, NOW()))) AS avg_duration,
                           SUM(TIMESTAMPDIFF(SECOND, time_start, COALESCE(time_end, NOW()))) AS total_duration
                    FROM session_history
                    WHERE time_start >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                    GROUP BY username
                    ORDER BY sessions DESC
                    LIMIT 20
                    """
                )
                top_users = cursor.fetchall()
                
                # Статистика по часам за последнюю неделю
                cursor.execute(
                    """
                    SELECT HOUR(time_start) AS hour,
                           COUNT(*) AS sessions
                    FROM session_history
                    WHERE time_start >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                    GROUP BY HOUR(time_start)
                    ORDER BY hour
                    """
                )
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

@bp.route('/api/sessions')
def api_sessions():
    """API: Получить активные VPN сессии"""
    try:
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT username,
                           outer_ip,
                           inner_ip,
                           time_start,
                           TIMESTAMPDIFF(SECOND, time_start, NOW()) AS duration_seconds
                    FROM session_history
                    WHERE time_end IS NULL
                    ORDER BY time_start DESC
                    """
                )
                sessions = cursor.fetchall() or []
                # Преобразуем datetime в строки для JSON
                for session in sessions:
                    if session.get('time_start') and hasattr(session['time_start'], 'isoformat'):
                        session['time_start'] = session['time_start'].isoformat()
                return jsonify({"status": "success", "count": len(sessions), "data": sessions})
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


@bp.route('/active-sessions')
def active_sessions():
    """Страница активных сессий с полной информацией"""
    try:
        raw_sessions = read_active_vpn_sessions()
        sessions = []
        for s in raw_sessions:
            ts = s.get('time_start')
            login_dt = _parse_login_time(ts)
            # попытка определить маршрутизатор по внутреннему IP, если отсутствует
            device_name = s.get('router') or ''
            if not device_name:
                device_name = _resolve_router_by_inner_ip(s.get('inner_ip') or '')
            sessions.append({
                'username': s.get('username') or '',
                'remote_address': s.get('outer_ip') or '',
                'inner_ip': s.get('inner_ip') or '',
                'device_name': device_name or '-',
                'login_time': login_dt,
                'login_iso': login_dt.isoformat() if login_dt else '',
                'duration': _format_duration_from(login_dt),
            })
        return render_template('vpn/active_sessions.html', sessions=sessions)
    except Exception as e:
        current_app.logger.error(f"VPN active sessions error: {e}")
        return render_template('vpn/active_sessions.html', sessions=[])


@bp.route('/today-sessions')
def today_sessions():
    """Страница сессий за сегодня с полной информацией"""
    try:
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT username,
                           outer_ip AS remote_address,
                           inner_ip,
                           NULL AS device_name,
                           time_start,
                           time_end,
                           TIMESTAMPDIFF(SECOND, time_start, COALESCE(time_end, NOW())) AS duration_seconds
                    FROM session_history 
                    WHERE DATE(time_start) = CURDATE()
                    ORDER BY time_start DESC
                """)
                sessions = cursor.fetchall()
                # обогащаем маршрутизатором по внутреннему IP
                for it in sessions:
                    if not it.get('device_name'):
                        it['device_name'] = _resolve_router_by_inner_ip(it.get('inner_ip')) or '-'
        return render_template('vpn/today_sessions.html', sessions=sessions)
    except Exception as e:
        current_app.logger.error(f"VPN today sessions error: {e}")
        return render_template('vpn/today_sessions.html', sessions=[])


@bp.route('/devices')
def devices():
    """Страница устройств MikroTik с адресами интерфейсов"""
    try:
        mikrotik_map = read_mikrotik_map()
        # Группируем по устройствам
        devices = {}
        for row in mikrotik_map:
            identity = row.get('identity', '')
            if not identity:
                continue
            if identity not in devices:
                devices[identity] = {
                    'identity': identity,
                    'interfaces': [],
                    'total_addresses': 0
                }
            devices[identity]['interfaces'].append({
                'ip': row.get('ip', ''),
                'iface': row.get('iface', ''),
                'type': row.get('type', '')
            })
            devices[identity]['total_addresses'] += 1
        
        devices_list = list(devices.values())
        return render_template('vpn/devices.html', devices=devices_list)
    except Exception as e:
        current_app.logger.error(f"VPN devices error: {e}")
        return render_template('vpn/devices.html', devices=[])


@bp.route('/user-stats')
def user_stats():
    """Страница статистики пользователей с выбором периода"""
    try:
        days = request.args.get('days', 30, type=int)
        if days not in [7, 30, 90, 365]:
            days = 30
        
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT username,
                           COUNT(*) as total_sessions,
                           AVG(TIMESTAMPDIFF(SECOND, time_start, COALESCE(time_end, NOW()))) as avg_duration_sec,
                           MAX(TIMESTAMPDIFF(SECOND, time_start, COALESCE(time_end, NOW()))) as max_duration_sec,
                           MAX(time_start) as last_login,
                           COUNT(*) / %s as avg_per_day
                    FROM session_history 
                    WHERE time_start >= DATE_SUB(NOW(), INTERVAL %s DAY)
                    GROUP BY username
                    ORDER BY total_sessions DESC
                """, (days, days))
                users = cursor.fetchall()
        
        # Форматируем длительности
        for user in users:
            if user.get('avg_duration_sec'):
                avg_sec = int(user['avg_duration_sec'])
                avg_h = avg_sec // 3600
                avg_m = (avg_sec % 3600) // 60
                user['avg_duration'] = f"{avg_h}ч {avg_m}м" if avg_h > 0 else f"{avg_m}м"
            else:
                user['avg_duration'] = '0м'
            
            if user.get('max_duration_sec'):
                max_sec = int(user['max_duration_sec'])
                max_h = max_sec // 3600
                max_m = (max_sec % 3600) // 60
                user['max_duration'] = f"{max_h}ч {max_m}м" if max_h > 0 else f"{max_m}м"
            else:
                user['max_duration'] = '0м'
            
            user['avg_per_day'] = round(user.get('avg_per_day', 0), 1)
        
        return render_template('vpn/user_stats.html', users=users, days=days)
    except Exception as e:
        current_app.logger.error(f"VPN user stats error: {e}")
        return render_template('vpn/user_stats.html', users=[], days=30)
