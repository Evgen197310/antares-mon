from flask import Blueprint, render_template, request, jsonify, current_app
from app.models.database import db_manager
from datetime import datetime, timedelta
import logging

bp = Blueprint('rdp', __name__)

def get_rdp_active_sessions():
    """Получить активные RDP сессии с интеграцией SMB данных"""
    state_map = {
        "0": "Активная", "1": "Подключён", "2": "Запрос подключения",
        "3": "Теневой режим", "4": "Отключён", "5": "Простой",
        "6": "Недоступна", "7": "Инициализация", "8": "Сброшена", "9": "Ожидание"
    }
    
    try:
        sessions = []
        with db_manager.get_connection('rdp') as conn_rdp:
            with db_manager.get_connection('smb') as conn_smb:
                with conn_rdp.cursor() as cursor:
                    cursor.execute("""
                        SELECT username, domain, collection_name, remote_host,
                               login_time, state, duration_seconds
                        FROM rdp_active_sessions
                        ORDER BY username ASC, collection_name ASC
                    """)
                    rows = cursor.fetchall()
                    
                    for row in rows:
                        # Получаем user_id из SMB базы с нормализацией имени
                        user_id = None
                        username = row.get('username')
                        if username:
                            base = str(username).lower().split('\\')[-1]
                            with conn_smb.cursor() as smb_cursor:
                                smb_cursor.execute(
                                    """
                                    SELECT id 
                                    FROM smb_users 
                                    WHERE LOWER(SUBSTRING_INDEX(username,'\\\\',-1)) = %s 
                                       OR LOWER(username) = %s
                                    LIMIT 1
                                    """,
                                    (base, base)
                                )
                                user_row = smb_cursor.fetchone()
                                if user_row:
                                    user_id = user_row['id']
                        
                        row["user_id"] = user_id
                        row["duration"] = row.get("duration_seconds")
                        state_code = str(row.get("state", ""))
                        row["state_label"] = state_map.get(state_code, f"Unknown({state_code})")
                        sessions.append(row)
        
        return sessions
    except Exception as e:
        current_app.logger.error(f"Error getting RDP active sessions: {e}")
        return []

@bp.route('/')
def index():
    """Главная страница RDP мониторинга"""
    try:
        sessions = get_rdp_active_sessions()
        
        # Группировка сессий по пользователям
        users_sessions = {}
        for session in sessions:
            username = session.get('username', 'Unknown')
            if username not in users_sessions:
                users_sessions[username] = []
            users_sessions[username].append(session)
        
        # Базовая статистика (приводим к ожиданиям шаблона)
        unique_users = len(users_sessions)
        unique_hosts = len({s.get('remote_host') for s in sessions if s.get('remote_host')})
        active_states = sum(1 for s in sessions if str(s.get('state')) in ['0', '1'])
        stats = {
            'unique_users': unique_users,
            'unique_hosts': unique_hosts,
            'active_states': active_states,
            'total_sessions': len(sessions)
        }
        
        return render_template('rdp/index.html', 
                             sessions=sessions,
                             users_sessions=users_sessions,
                             active_sessions=sessions,
                             stats=stats)
    except Exception as e:
        current_app.logger.error(f"RDP index error: {e}")
        return render_template('rdp/index.html', 
                             sessions=[], 
                             users_sessions={}, 
                             active_sessions=[],
                             stats={'unique_users': 0, 'unique_hosts': 0, 'active_states': 0, 'total_sessions': 0})

@bp.route('/sessions-history')
def sessions_history():
    """История RDP: сводка по пользователям (как в исходном проекте)."""
    try:
        with db_manager.get_connection('rdp') as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT 
                        username,
                        MAX(login_time)   AS last_login,
                        MAX(logout_time)  AS last_logout,
                        COUNT(*)          AS total_sessions
                    FROM rdp_session_history
                    GROUP BY username
                    ORDER BY last_login DESC
                    """
                )
                users = cursor.fetchall()

                return render_template('rdp/sessions_history.html', users=users)
    except Exception as e:
        current_app.logger.error(f"RDP sessions history error: {e}")
        return render_template('rdp/sessions_history.html', users=[])

@bp.route('/user/<username>')
def user_history(username):
    """Детальная история RDP сессий пользователя"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = 50
        offset = (page - 1) * per_page

        # Фильтры периода и хоста
        date_from_arg = request.args.get('date_from')
        date_to_arg = request.args.get('date_to')
        host_filter = request.args.get('host_filter', '', type=str)

        # Без ограничения по датам по умолчанию (берём всю историю)
        date_from = datetime.strptime(date_from_arg, '%Y-%m-%d') if date_from_arg else None
        date_to_input = datetime.strptime(date_to_arg, '%Y-%m-%d') if date_to_arg else None
        # Для верхней границы используем полуинтервал: login_time < date_to + 1 день
        date_to_exclusive = (date_to_input + timedelta(days=1)) if date_to_input else None

        with db_manager.get_connection('rdp') as conn:
            with conn.cursor() as cursor:
                # Динамические условия
                where = ["username = %s"]
                params = [username]
                if date_from:
                    where.append("login_time >= %s")
                    params.append(date_from)
                if date_to_exclusive:
                    where.append("login_time < %s")
                    params.append(date_to_exclusive)
                if host_filter:
                    where.append("remote_host LIKE %s")
                    params.append(f"%{host_filter}%")

                where_sql = " AND ".join(where)

                # Всего записей
                cursor.execute(f"""
                    SELECT COUNT(*) as total
                    FROM rdp_session_history
                    WHERE {where_sql}
                """, params)
                total = cursor.fetchone()['total']

                # Данные страницы
                cursor.execute(f"""
                    SELECT username, domain, collection_name, remote_host,
                           login_time, logout_time, connection_type, duration_seconds
                    FROM rdp_session_history
                    WHERE {where_sql}
                    ORDER BY login_time DESC
                    LIMIT %s OFFSET %s
                """, params + [per_page, offset])
                sessions = cursor.fetchall()

                # Расширенная статистика под нужды шаблона
                cursor.execute(f"""
                    SELECT 
                        COUNT(*)                            AS total_sessions,
                        COUNT(DISTINCT remote_host)         AS unique_hosts,
                        COUNT(DISTINCT collection_name)     AS unique_collections,
                        AVG(duration_seconds)               AS avg_duration,
                        MAX(login_time)                     AS last_login
                    FROM rdp_session_history
                    WHERE {where_sql}
                """, params)
                user_stats = cursor.fetchone() or {}

                # Пагинация (количество страниц)
                total_pages = max(1, (total + per_page - 1) // per_page)
                # Окно отображаемых страниц (по 3 слева/справа)
                start_page = max(1, page - 3)
                end_page = min(total_pages, page + 3)
                page_numbers = list(range(start_page, end_page + 1))
                has_prev = page > 1
                has_next = page < total_pages

                return render_template(
                    'rdp/user_history.html',
                    username=username,
                    sessions=sessions,
                    user_stats=user_stats,
                    # значения фильтров обратно в форму
                    date_from=(date_from.strftime('%Y-%m-%d') if date_from else ''),
                    date_to=(date_to_input.strftime('%Y-%m-%d') if date_to_input else ''),
                    host_filter=host_filter,
                    # пагинация
                    page=page,
                    total_pages=total_pages,
                    page_size=per_page,
                    total=total,
                    page_numbers=page_numbers,
                    has_prev=has_prev,
                    has_next=has_next
                )
    except Exception as e:
        current_app.logger.error(f"RDP user history error: {e}")
        return render_template('rdp/user_history.html', 
                             username=username, 
                              sessions=[], 
                             user_stats={},
                             date_from=None,
                             date_to=None,
                             host_filter=None,
                             page=1,
                             total_pages=1)

@bp.route('/active-sessions')
def active_sessions():
    """Детальный просмотр активных RDP сессий"""
    try:
        sessions = get_rdp_active_sessions()
        
        # Группировка сессий по пользователям
        users_sessions = {}
        for session in sessions:
            username = session.get('username', 'Unknown')
            if username not in users_sessions:
                users_sessions[username] = []
            users_sessions[username].append(session)
        
        return render_template('rdp/active_sessions.html',
                             sessions=sessions,
                             users_sessions=users_sessions)
    except Exception as e:
        current_app.logger.error(f"RDP active sessions error: {e}")
        return render_template('rdp/active_sessions.html', 
                             sessions=[], 
                             users_sessions={})

# API endpoints для RDP
@bp.route('/api/sessions')
def api_sessions():
    """API: Получить активные RDP сессии"""
    try:
        sessions = get_rdp_active_sessions()
        
        # Преобразуем datetime в строки для JSON
        for session in sessions:
            if session.get('login_time'):
                session['login_time'] = session['login_time'].isoformat()
        
        return jsonify({
            "status": "success",
            "count": len(sessions),
            "data": sessions
        })
    except Exception as e:
        current_app.logger.error(f"RDP API sessions error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@bp.route('/api/user/<username>/stats')
def api_user_stats(username):
    """API: Статистика пользователя RDP"""
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
                
                return jsonify({
                    "status": "success",
                    "data": {
                        "username": username,
                        "active_sessions": active_count,
                        "sessions_last_30_days": total_count,
                        "timestamp": datetime.now().isoformat()
                    }
                })
    except Exception as e:
        current_app.logger.error(f"RDP API user stats error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
