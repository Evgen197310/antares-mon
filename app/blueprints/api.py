from flask import Blueprint, jsonify, request, current_app
from app.models.database import db_manager
from datetime import datetime, timedelta
import logging
import os

def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

def _get_version_info():
    """Возвращает (version, last_update_iso).
    Источник истины — файл VERSION в корне проекта:
      - version = содержимое VERSION (например, "2.1").
      - last_update = mtime файла VERSION.
    Фоллбэки (если VERSION отсутствует):
      - version = 'unknown'
      - last_update = максимальный mtime среди файлов кода/шаблонов; если не получилось — текущее время.
    """
    root = _repo_root()
    version_path = os.path.join(root, 'VERSION')

    version = None
    last_update = None

    if os.path.isfile(version_path):
        try:
            with open(version_path, 'r', encoding='utf-8') as f:
                version = (f.read() or '').strip()
        except Exception:
            version = None
        try:
            mtime = os.path.getmtime(version_path)
            last_update = datetime.fromtimestamp(mtime).isoformat()
        except Exception:
            last_update = None

    if not version:
        version = 'unknown'

    if not last_update:
        # Ищем максимальный mtime по основным директориям проекта
        try:
            candidates = [
                os.path.join(root, 'app'),
                os.path.join(root, 'templates'),
                os.path.join(root, 'static'),
            ]
            max_mtime = 0
            for base in candidates:
                if not os.path.isdir(base):
                    continue
                for dirpath, _dirnames, filenames in os.walk(base):
                    for fn in filenames:
                        p = os.path.join(dirpath, fn)
                        try:
                            mt = os.path.getmtime(p)
                            if mt > max_mtime:
                                max_mtime = mt
                        except Exception:
                            continue
            if max_mtime > 0:
                last_update = datetime.fromtimestamp(max_mtime).isoformat()
        except Exception:
            last_update = None

    if not last_update:
        last_update = datetime.now().isoformat()

    return version, last_update

bp = Blueprint('api', __name__)

@bp.route('/')
def index():
    """API информация"""
    version, last_update = _get_version_info()
    return jsonify({
        "name": "Monitoring API",
        "version": version,
        "status": "active",
        "description": "Unified Network Monitoring API",
        "last_update": last_update,
        "endpoints": {
            "vpn": {
                "/api/vpn/sessions": "Активные VPN сессии",
                "/api/vpn/history": "История VPN сессий",
                "/api/vpn/stats": "Статистика VPN"
            },
            "rdp": {
                "/api/rdp/sessions": "Активные RDP сессии", 
                "/api/rdp/history": "История RDP сессий",
                "/api/rdp/user/<username>": "Статистика пользователя RDP"
            },
            "smb": {
                "/api/smb/sessions": "Активные SMB сессии",
                "/api/smb/files": "Открытые файлы SMB",
                "/api/smb/users": "Пользователи SMB",
                "/api/smb/stats": "Статистика SMB"
            }
        }
    })

@bp.route('/docs')
def docs():
    """API документация"""
    version, last_update = _get_version_info()
    return jsonify({
        "title": "Monitoring API Documentation",
        "version": version,
        "description": "REST API для системы мониторинга сетевой инфраструктуры",
        "base_url": "/api",
        "authentication": "None required",
        "response_format": "JSON",
        "last_update": last_update,
        "endpoints": {
            "GET /api/": "Информация об API",
            "GET /api/docs": "Документация API",
            "GET /api/vpn/*": "VPN мониторинг endpoints",
            "GET /api/rdp/*": "RDP мониторинг endpoints", 
            "GET /api/smb/*": "SMB мониторинг endpoints"
        }
    })

# === VPN API ===

@bp.route('/vpn/sessions')
def vpn_sessions():
    """Получить активные VPN сессии"""
    try:
        # Читаем активные сессии из CSV файла, как в исходном проекте
        state_file = '/var/log/mikrotik/ikev2_active.csv'
        sessions = []
        with open(state_file, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split(',')
                if len(parts) == 4:
                    username, outer_ip, inner_ip, time_start = parts
                    sessions.append({
                        'username': username,
                        'outer_ip': outer_ip,
                        'inner_ip': inner_ip,
                        'time_start': time_start
                    })
        return jsonify({
            "status": "success",
            "count": len(sessions),
            "data": sessions
        })
    except Exception as e:
        current_app.logger.error(f"VPN sessions API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/vpn/history')
def vpn_history():
    """История VPN сессий"""
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        username = request.args.get('username')
        
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cursor:
                where_clause = ""
                params = []
                
                if username:
                    where_clause = "WHERE username = %s"
                    params.append(username)
                
                cursor.execute(f"""
                    SELECT username, outer_ip, inner_ip, time_start, time_end, duration
                    FROM session_history 
                    {where_clause}
                    ORDER BY time_start DESC
                    LIMIT %s OFFSET %s
                """, params + [limit, offset])
                
                sessions = cursor.fetchall()
                
                for session in sessions:
                    if session.get('time_start'):
                        session['time_start'] = session['time_start'].isoformat()
                    if session.get('time_end'):
                        session['time_end'] = session['time_end'].isoformat()
                
                return jsonify({
                    "status": "success",
                    "count": len(sessions),
                    "limit": limit,
                    "offset": offset,
                    "data": sessions
                })
    except Exception as e:
        current_app.logger.error(f"VPN history API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/vpn/stats')
def vpn_stats():
    """Статистика VPN"""
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
        current_app.logger.error(f"VPN stats API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# === RDP API ===

@bp.route('/rdp/sessions')
def rdp_sessions():
    """Получить активные RDP сессии"""
    try:
        state_map = {
            "0": "Активная", "1": "Подключён", "2": "Запрос подключения",
            "3": "Теневой режим", "4": "Отключён", "5": "Простой",
            "6": "Недоступна", "7": "Инициализация", "8": "Сброшена", "9": "Ожидание"
        }
        
        with db_manager.get_connection('rdp') as conn_rdp:
            with db_manager.get_connection('smb') as conn_smb:
                with conn_rdp.cursor() as cursor:
                    cursor.execute("""
                        SELECT username, domain, collection_name, remote_host,
                               login_time, state, duration_seconds
                        FROM rdp_active_sessions
                        ORDER BY username ASC, collection_name ASC
                    """)
                    sessions = cursor.fetchall()
                    
                    # Добавляем user_id из SMB базы
                    for session in sessions:
                        session['state_label'] = state_map.get(str(session.get('state', '')), 'Unknown')
                        if session.get('login_time'):
                            session['login_time'] = session['login_time'].isoformat()
                        
                        username = session.get('username')
                        if username:
                            with conn_smb.cursor() as smb_cursor:
                                smb_cursor.execute("SELECT id FROM smb_users WHERE username = %s", (username,))
                                user_row = smb_cursor.fetchone()
                                session['user_id'] = user_row['id'] if user_row else None
                    
                    return jsonify({
                        "status": "success",
                        "count": len(sessions),
                        "data": sessions
                    })
    except Exception as e:
        current_app.logger.error(f"RDP sessions API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/rdp/history')
def rdp_history():
    """История RDP сессий"""
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        username = request.args.get('username')
        
        with db_manager.get_connection('rdp') as conn:
            with conn.cursor() as cursor:
                where_clause = ""
                params = []
                
                if username:
                    where_clause = "WHERE username = %s"
                    params.append(username)
                
                cursor.execute(f"""
                    SELECT username, domain, collection_name, remote_host, login_time, connection_type
                    FROM rdp_session_history 
                    {where_clause}
                    ORDER BY login_time DESC
                    LIMIT %s OFFSET %s
                """, params + [limit, offset])
                
                sessions = cursor.fetchall()
                
                for session in sessions:
                    if session.get('login_time'):
                        session['login_time'] = session['login_time'].isoformat()
                
                return jsonify({
                    "status": "success",
                    "count": len(sessions),
                    "limit": limit,
                    "offset": offset,
                    "data": sessions
                })
    except Exception as e:
        current_app.logger.error(f"RDP history API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/rdp/user/<username>')
def rdp_user_stats(username):
    """Статистика пользователя RDP"""
    try:
        with db_manager.get_connection('rdp') as conn:
            with conn.cursor() as cursor:
                # Активные сессии пользователя
                cursor.execute("""
                    SELECT COUNT(*) as active 
                    FROM rdp_active_sessions 
                    WHERE username = %s
                """, (username,))
                active_count = cursor.fetchone()['active']
                
                # Всего сессий за последние 30 дней
                cursor.execute("""
                    SELECT COUNT(*) as total 
                    FROM rdp_session_history 
                    WHERE username = %s AND login_time >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                """, (username,))
                total_count = cursor.fetchone()['total']
                
                # Последняя активность
                cursor.execute("""
                    SELECT login_time 
                    FROM rdp_session_history 
                    WHERE username = %s 
                    ORDER BY login_time DESC 
                    LIMIT 1
                """, (username,))
                last_activity = cursor.fetchone()
                
                return jsonify({
                    "status": "success",
                    "data": {
                        "username": username,
                        "active_sessions": active_count,
                        "sessions_last_30_days": total_count,
                        "last_activity": last_activity['login_time'].isoformat() if last_activity and last_activity.get('login_time') else None,
                        "timestamp": datetime.now().isoformat()
                    }
                })
    except Exception as e:
        current_app.logger.error(f"RDP user stats API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# === SMB API ===

@bp.route('/smb/sessions')
def smb_sessions():
    """Активные SMB сессии"""
    try:
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT u.username, f.path, c.host, s.open_time, s.last_seen,
                           s.initial_size, s.session_id
                    FROM active_smb_sessions s
                    JOIN smb_users u ON s.user_id = u.id
                    JOIN smb_files f ON s.file_id = f.id
                    JOIN smb_clients c ON s.client_id = c.id
                    ORDER BY s.last_seen DESC
                """)
                sessions = cursor.fetchall()
                
                for session in sessions:
                    if session.get('open_time'):
                        session['open_time'] = session['open_time'].isoformat()
                    if session.get('last_seen'):
                        session['last_seen'] = session['last_seen'].isoformat()
                
                return jsonify({
                    "status": "success",
                    "count": len(sessions),
                    "data": sessions
                })
    except Exception as e:
        current_app.logger.error(f"SMB sessions API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/smb/files')
def smb_files():
    """Открытые файлы SMB"""
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT f.id, f.path, f.norm_path, COUNT(s.file_id) as active_sessions
                    FROM smb_files f
                    LEFT JOIN active_smb_sessions s ON f.id = s.file_id
                    GROUP BY f.id, f.path, f.norm_path
                    HAVING active_sessions > 0
                    ORDER BY active_sessions DESC
                    LIMIT %s OFFSET %s
                """, (limit, offset))
                
                files = cursor.fetchall()
                
                return jsonify({
                    "status": "success",
                    "count": len(files),
                    "limit": limit,
                    "offset": offset,
                    "data": files
                })
    except Exception as e:
        current_app.logger.error(f"SMB files API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/smb/users')
def smb_users():
    """Пользователи SMB"""
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT u.id, u.username, COUNT(s.user_id) as active_sessions
                    FROM smb_users u
                    LEFT JOIN active_smb_sessions s ON u.id = s.user_id
                    GROUP BY u.id, u.username
                    ORDER BY active_sessions DESC, u.username ASC
                    LIMIT %s OFFSET %s
                """, (limit, offset))
                
                users = cursor.fetchall()
                
                return jsonify({
                    "status": "success",
                    "count": len(users),
                    "limit": limit,
                    "offset": offset,
                    "data": users
                })
    except Exception as e:
        current_app.logger.error(f"SMB users API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/smb/stats')
def smb_stats():
    """Статистика SMB"""
    try:
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                # Активные сессии
                cursor.execute("SELECT COUNT(*) as active FROM active_smb_sessions")
                active_sessions = cursor.fetchone()['active']
                
                # Активные пользователи
                cursor.execute("""
                    SELECT COUNT(DISTINCT user_id) as active_users 
                    FROM active_smb_sessions
                """)
                active_users = cursor.fetchone()['active_users']
                
                # Открытые файлы
                cursor.execute("""
                    SELECT COUNT(DISTINCT file_id) as open_files 
                    FROM active_smb_sessions
                """)
                open_files = cursor.fetchone()['open_files']
                
                # Всего пользователей
                cursor.execute("SELECT COUNT(*) as total_users FROM smb_users")
                total_users = cursor.fetchone()['total_users']
                
                # Всего файлов
                cursor.execute("SELECT COUNT(*) as total_files FROM smb_files")
                total_files = cursor.fetchone()['total_files']
                
                return jsonify({
                    "status": "success",
                    "data": {
                        "active_sessions": active_sessions,
                        "active_users": active_users,
                        "open_files": open_files,
                        "total_users": total_users,
                        "total_files": total_files,
                        "timestamp": datetime.now().isoformat()
                    }
                })
    except Exception as e:
        current_app.logger.error(f"SMB stats API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# === Общие API функции ===

@bp.route('/health')
def health():
    """Проверка состояния API"""
    try:
        # Проверяем подключения к базам данных
        db_status = {}
        
        for db_type in ['vpn', 'rdp', 'smb']:
            try:
                with db_manager.get_connection(db_type) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        db_status[db_type] = "healthy"
            except Exception as e:
                db_status[db_type] = f"error: {str(e)}"
        
        overall_status = "healthy" if all(status == "healthy" for status in db_status.values()) else "degraded"
        # Версия, последнее обновление и аптайм
        version, last_update = _get_version_info()
        started_at = current_app.config.get('STARTED_AT')
        try:
            uptime_seconds = int((datetime.now() - started_at).total_seconds()) if started_at else 0
        except Exception:
            uptime_seconds = 0
        
        return jsonify({
            "status": overall_status,
            "timestamp": datetime.now().isoformat(),
            "databases": db_status,
            "version": version,
            "last_update": last_update,
            "uptime_seconds": uptime_seconds
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500

@bp.route('/status')
def status():
    """Общий статус системы мониторинга"""
    try:
        status_data = {}
        
        # VPN статистика
        try:
            with db_manager.get_connection('vpn') as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) as active FROM session_history WHERE time_end IS NULL")
                    status_data['vpn'] = {"active_sessions": cursor.fetchone()['active']}
        except Exception as e:
            status_data['vpn'] = {"error": str(e)}
        
        # RDP статистика
        try:
            with db_manager.get_connection('rdp') as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) as active FROM rdp_active_sessions")
                    status_data['rdp'] = {"active_sessions": cursor.fetchone()['active']}
        except Exception as e:
            status_data['rdp'] = {"error": str(e)}
        
        # SMB статистика
        try:
            with db_manager.get_connection('smb') as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) as active FROM active_smb_sessions")
                    cursor.execute("SELECT COUNT(DISTINCT user_id) as users FROM active_smb_sessions")
                    active_sessions = cursor.fetchone()['active']
                    cursor.execute("SELECT COUNT(DISTINCT user_id) as users FROM active_smb_sessions")
                    active_users = cursor.fetchone()['users']
                    status_data['smb'] = {
                        "active_sessions": active_sessions,
                        "active_users": active_users
                    }
        except Exception as e:
            status_data['smb'] = {"error": str(e)}
        
        return jsonify({
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "data": status_data
        })
    except Exception as e:
        current_app.logger.error(f"Status API error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
