from flask import Blueprint, render_template, request, jsonify, current_app, send_file
from app.models.database import db_manager
from datetime import datetime, timedelta
import logging
import os
import tempfile
import paramiko
from urllib.parse import quote
import traceback

bp = Blueprint('smb', __name__)

@bp.route('/debug-ping')
def debug_ping():
    return 'smb-ok'

@bp.route('/debug-ssh')
def debug_ssh():
    """Проверка SSH-подключения (отладка). Не возвращает секреты."""
    try:
        cfg = current_app.config.get('SMB_SSH', {}) or {}
        info = {
            'host': cfg.get('host'),
            'user': cfg.get('user'),
            'port': cfg.get('port', 22),
            'has_key_file': bool(cfg.get('key_file')),
            'has_password': bool(cfg.get('password')),
        }
        ssh = get_ssh_connection()
        if not ssh:
            return jsonify({'status': 'error', 'message': 'ssh_connect_failed', 'info': info}), 500
        try:
            # Проба открыть SFTP и закрыть
            sftp = ssh.open_sftp()
            sftp.listdir('.')  # лёгкая операция
            sftp.close()
            ssh.close()
            return jsonify({'status': 'ok', 'info': info})
        except Exception as e:
            try:
                ssh.close()
            except Exception:
                pass
            current_app.logger.error(f"SSH SFTP error: {e}")
            return jsonify({'status': 'error', 'message': 'sftp_failed', 'error': str(e), 'info': info}), 500
    except Exception as e:
        current_app.logger.error(f"debug_ssh error: {e}")
        return jsonify({'status': 'error', 'message': 'internal_error', 'error': str(e)}), 500

def normalize_username(username):
    """Нормализация имени пользователя"""
    if not username:
        return username
    return username.lower().replace('\\', '_').replace('/', '_')

def _beautify_filename(fname: str) -> str:
    """Только первая буква заглавная, остальное маленькими, расширение нижним регистром."""
    if not fname:
        return ''
    name, ext = os.path.splitext(fname)
    name = (name or '').strip().lower().capitalize()
    ext = (ext or '').lower()
    return name + ext

def _extract_display_name_from_path(path_value: str) -> str:
    """Получить читаемое имя файла из хранимого пути.
    Особый случай: в БД путь может храниться как 'F__shares_pau$_...'
    где '__' означает разделитель каталога. Преобразуем и берём последний сегмент.
    """
    if not path_value:
        return ''
    p = str(path_value)
    # Нормализуем потенциальные разделители: '__' -> '\\'
    p = p.replace('__', '\\').replace('/', '\\')
    # Берём последний сегмент
    last = p.split('\\')[-1]
    return _beautify_filename(last)

def get_ssh_connection():
    """Получить SSH подключение к SMB серверу"""
    try:
        config = current_app.config
        ssh_config = (config.get('SMB_SSH') or {}).copy()
        # Fallback: legacy mapping remote_host.smb_server
        if not ssh_config or not ssh_config.get('host'):
            legacy = (config.get('REMOTE_HOST') or {}).get('smb_server') or {}
            if legacy:
                ssh_config.setdefault('host', legacy.get('ssh_host'))
                ssh_config.setdefault('user', legacy.get('ssh_user'))
                ssh_config.setdefault('key_file', legacy.get('ssh_key'))
                if legacy.get('ssh_port'):
                    ssh_config.setdefault('port', legacy.get('ssh_port'))
        
        host = ssh_config.get('host')
        user = ssh_config.get('user')
        key_file = ssh_config.get('key_file')
        password = ssh_config.get('password')  # опционально
        port = ssh_config.get('port', 22)

        if not host or not user:
            current_app.logger.error("SMB_SSH config error: 'host' and 'user' are required")
            return None

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        connect_kwargs = {
            'hostname': host,
            'username': user,
            'timeout': 15,
            'port': port,
            'allow_agent': False,
            'look_for_keys': False,
        }
        if key_file:
            connect_kwargs['key_filename'] = key_file
            # для ключа пароль обычно не нужен
        elif password:
            connect_kwargs['password'] = password
        else:
            # ни ключа, ни пароля — скорее всего не подключимся
            current_app.logger.error("SMB_SSH config error: either 'key_file' or 'password' must be provided")
            return None

        ssh.connect(**connect_kwargs)
        
        return ssh
    except Exception as e:
        current_app.logger.error(f"SSH connection error: {e}")
        return None

@bp.route('/')
def index():
    """Главная страница SMB мониторинга"""
    try:
        search_user = request.args.get('search_user', '').strip()
        search_file = request.args.get('search_file', '').strip()
        
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                # Получаем пользователей с активными сессиями
                users_query = """
                    SELECT u.id, u.username, COUNT(s.user_id) as open_files_count,
                           MAX(s.last_seen) as last_activity
                    FROM smb_users u
                    LEFT JOIN active_smb_sessions s ON u.id = s.user_id
                    GROUP BY u.id, u.username
                """
                params = []
                
                if search_user:
                    users_query += " HAVING u.username LIKE %s"
                    params.append(f"%{search_user}%")
                
                users_query += " ORDER BY open_files_count DESC, u.username ASC LIMIT 50"
                cursor.execute(users_query, params)
                users = cursor.fetchall()
                
                # Последние открытые файлы (из активных сессий)
                recent_query = """
                    SELECT f.id as file_id, f.path, u.id as user_id, u.username,
                           s.open_time, s.initial_size, s.last_seen
                    FROM active_smb_sessions s
                    JOIN smb_files f ON s.file_id = f.id
                    JOIN smb_users u ON s.user_id = u.id
                """
                recent_params = []
                if search_file:
                    recent_query += " WHERE f.path LIKE %s"
                    recent_params.append(f"%{search_file}%")
                recent_query += " ORDER BY s.last_seen DESC LIMIT 10"
                cursor.execute(recent_query, recent_params)
                recent = cursor.fetchall()
                
                # Подготовка структуры, ожидаемой шаблоном
                files = []
                for r in recent:
                    item = dict(r)
                    item['id'] = r['file_id']
                    item['filename'] = os.path.basename(r['path']) if r.get('path') else None
                    item['file_size'] = r.get('initial_size')
                    files.append(item)
                
                # Статистика
                cursor.execute("SELECT COUNT(*) as total FROM active_smb_sessions")
                active_sessions = cursor.fetchone()['total']
                
                cursor.execute("SELECT COUNT(DISTINCT user_id) as total FROM active_smb_sessions")
                active_users = cursor.fetchone()['total']
                
                cursor.execute("SELECT COUNT(DISTINCT file_id) as total FROM active_smb_sessions")
                open_files = cursor.fetchone()['total']
                
                return render_template('smb/index.html',
                                     users=users,
                                     files=files,
                                     search_user=search_user,
                                     search_file=search_file,
                                     stats={
                                         'active_sessions': active_sessions,
                                         'active_users': active_users,
                                         'open_files': open_files
                                     })
    except Exception as e:
        current_app.logger.error(f"SMB index error: {e}")
        return render_template('smb/index.html', users=[], files=[], stats={})

@bp.route('/files-open-now')
def files_open_now():
    """Открытые в данный момент файлы"""
    try:
        if request.args.get('ping') == '1':
            return 'pong'
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT s.session_id, u.username, f.path, f.id AS file_id, c.host,
                           s.open_time, s.last_seen, s.initial_size
                    FROM active_smb_sessions s
                    JOIN smb_users u ON s.user_id = u.id
                    JOIN smb_files f ON s.file_id = f.id
                    JOIN smb_clients c ON s.client_id = c.id
                    ORDER BY s.last_seen DESC
                """)
                sessions = cursor.fetchall()
                # Режим отладки: вернуть JSON
                if request.args.get('format') == 'json':
                    # Преобразуем datetime в строки для JSON
                    out = []
                    for s in sessions:
                        s2 = dict(s)
                        if s2.get('open_time'):
                            s2['open_time'] = s2['open_time'].isoformat()
                        if s2.get('last_seen'):
                            s2['last_seen'] = s2['last_seen'].isoformat()
                        out.append(s2)
                    return jsonify({"status": "success", "count": len(out), "data": out})

                try:
                    return render_template('smb/open_now_table.html', sessions=sessions)
                except Exception as re:
                    current_app.logger.error(f"Template render error: {re}")
                    return "Render error\n" + traceback.format_exc(), 500
    except Exception as e:
        current_app.logger.error(f"SMB files open now error: {e}")
        # В отладочном режиме возвращаем текст ошибки
        if request.args.get('format') == 'json':
            return jsonify({"status": "error", "message": str(e)}), 500
        return f"SMB files open now error: {e}", 500

@bp.route('/user/<int:user_id>')
def user_detail(user_id):
    """Детальная страница пользователя SMB"""
    try:
        page = request.args.get('page', 1, type=int)
        days = request.args.get('days', 7, type=int)
        activity = request.args.get('activity', 'all')  # all, active, history
        per_page = 50
        offset = (page - 1) * per_page
        
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                # Получаем информацию о пользователе
                cursor.execute("SELECT username FROM smb_users WHERE id = %s", (user_id,))
                user = cursor.fetchone()
                if not user:
                    return "Пользователь не найден", 404
                
                # Активные сессии
                cursor.execute("""
                    SELECT f.id AS file_id, f.path, c.host, s.open_time, s.last_seen, s.initial_size
                    FROM active_smb_sessions s
                    JOIN smb_files f ON s.file_id = f.id
                    JOIN smb_clients c ON s.client_id = c.id
                    WHERE s.user_id = %s
                    ORDER BY s.last_seen DESC
                """, (user_id,))
                active_sessions = cursor.fetchall()
                
                # История сессий
                date_from = datetime.now() - timedelta(days=days)
                history_query = """
                    SELECT f.id AS file_id, f.path, h.open_time, h.close_time, h.initial_size, h.final_size
                    FROM smb_session_history h
                    JOIN smb_files f ON h.file_id = f.id
                    WHERE h.user_id = %s AND h.open_time >= %s
                    ORDER BY h.open_time DESC
                    LIMIT %s OFFSET %s
                """
                cursor.execute(history_query, (user_id, date_from, per_page, offset))
                history_sessions = cursor.fetchall()
                
                # Общее количество записей истории
                cursor.execute("""
                    SELECT COUNT(*) as total
                    FROM smb_session_history
                    WHERE user_id = %s AND open_time >= %s
                """, (user_id, date_from))
                total_history = cursor.fetchone()['total']
                
                # Статистика пользователя
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_sessions,
                        COUNT(DISTINCT file_id) as unique_files,
                        MIN(open_time) as first_session,
                        MAX(open_time) as last_session
                    FROM smb_session_history
                    WHERE user_id = %s AND open_time >= %s
                """, (user_id, date_from))
                stats = cursor.fetchone()
                
                # Пагинация
                has_prev = page > 1
                has_next = offset + per_page < total_history
                prev_num = page - 1 if has_prev else None
                next_num = page + 1 if has_next else None
                
                # Проверяем RDP активность пользователя
                rdp_sessions = []
                try:
                    with db_manager.get_connection('rdp') as rdp_conn:
                        with rdp_conn.cursor() as rdp_cursor:
                            rdp_cursor.execute("""
                                SELECT login_time, remote_host, state
                                FROM rdp_active_sessions
                                WHERE username = %s
                                ORDER BY login_time DESC
                                LIMIT 5
                            """, (user['username'],))
                            rdp_sessions = rdp_cursor.fetchall()
                except:
                    pass
                
                return render_template('smb/user_detail.html',
                                     user=user,
                                     user_id=user_id,
                                     active_sessions=active_sessions,
                                     history_sessions=history_sessions,
                                     rdp_sessions=rdp_sessions,
                                     stats=stats,
                                     days=days,
                                     activity=activity,
                                     page=page,
                                     per_page=per_page,
                                     total_history=total_history,
                                     has_prev=has_prev,
                                     has_next=has_next,
                                     prev_num=prev_num,
                                     next_num=next_num)
    except Exception as e:
        current_app.logger.error(f"SMB user detail error: {e}")
        return "Ошибка загрузки данных пользователя", 500

@bp.route('/file/<int:file_id>')
def file_detail(file_id):
    """Детальная страница файла SMB"""
    try:
        page = request.args.get('page', 1, type=int)
        days = request.args.get('days', 7, type=int)
        per_page = 50
        offset = (page - 1) * per_page
        
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                # Получаем информацию о файле
                cursor.execute("SELECT path, norm_path FROM smb_files WHERE id = %s", (file_id,))
                file_info = cursor.fetchone()
                if not file_info:
                    return "Файл не найден", 404
                
                # Активные сессии
                cursor.execute("""
                    SELECT u.username, c.host, s.open_time, s.last_seen, s.initial_size
                    FROM active_smb_sessions s
                    JOIN smb_users u ON s.user_id = u.id
                    JOIN smb_clients c ON s.client_id = c.id
                    WHERE s.file_id = %s
                    ORDER BY s.last_seen DESC
                """, (file_id,))
                active_sessions = cursor.fetchall()
                
                # История сессий
                date_from = datetime.now() - timedelta(days=days)
                cursor.execute("""
                    SELECT u.username, h.open_time, h.close_time, h.initial_size, h.final_size
                    FROM smb_session_history h
                    JOIN smb_users u ON h.user_id = u.id
                    WHERE h.file_id = %s AND h.open_time >= %s
                    ORDER BY h.open_time DESC
                    LIMIT %s OFFSET %s
                """, (file_id, date_from, per_page, offset))
                history_sessions = cursor.fetchall()
                
                # Общее количество записей истории
                cursor.execute("""
                    SELECT COUNT(*) as total
                    FROM smb_session_history
                    WHERE file_id = %s AND open_time >= %s
                """, (file_id, date_from))
                total_history = cursor.fetchone()['total']
                
                # Статистика файла
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_sessions,
                        COUNT(DISTINCT user_id) as unique_users,
                        MIN(open_time) as first_access,
                        MAX(open_time) as last_access
                    FROM smb_session_history
                    WHERE file_id = %s AND open_time >= %s
                """, (file_id, date_from))
                stats = cursor.fetchone()
                
                # Пагинация
                has_prev = page > 1
                has_next = offset + per_page < total_history
                prev_num = page - 1 if has_prev else None
                next_num = page + 1 if has_next else None
                
                return render_template('smb/file_detail.html',
                                     file_info=file_info,
                                     file_id=file_id,
                                     active_sessions=active_sessions,
                                     history_sessions=history_sessions,
                                     stats=stats,
                                     days=days,
                                     page=page,
                                     per_page=per_page,
                                     total_history=total_history,
                                     has_prev=has_prev,
                                     has_next=has_next,
                                     prev_num=prev_num,
                                     next_num=next_num)
    except Exception as e:
        current_app.logger.error(f"SMB file detail error: {e}")
        return "Ошибка загрузки данных файла", 500

@bp.route('/file/<int:file_id>/download')
def download_file(file_id):
    """Скачивание файла через SSH"""
    try:
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT path FROM smb_files WHERE id = %s", (file_id,))
                file_info = cursor.fetchone()
                if not file_info:
                    return "Файл не найден", 404
                
                file_path = file_info['path']
                
        # Подключение по SSH и скачивание файла
        ssh = get_ssh_connection()
        if not ssh:
            return "Ошибка SSH подключения", 500
        
        try:
            sftp = ssh.open_sftp()
            
            # Создаем временный файл
            temp_file = tempfile.NamedTemporaryFile(delete=False)
            temp_path = temp_file.name
            temp_file.close()
            
            # Скачиваем файл
            sftp.get(file_path, temp_path)
            sftp.close()
            ssh.close()
            
            # Определяем имя файла для скачивания (только имя, первая буква заглавная)
            filename = _extract_display_name_from_path(file_path)

            from flask import after_this_request
            @after_this_request
            def cleanup(response):
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception as ce:
                    current_app.logger.warning(f"Temp file cleanup error: {ce}")
                return response
            
            return send_file(temp_path, 
                           as_attachment=True, 
                           download_name=filename,
                           mimetype='application/octet-stream')
        
        except Exception as e:
            try:
                ssh.close()
            except Exception:
                pass
            current_app.logger.error(f"File download error: {e}")
            return f"Ошибка скачивания файла: {e}", 500
            
    except Exception as e:
        current_app.logger.error(f"SMB download error: {e}")
        return "Ошибка при подготовке скачивания", 500
