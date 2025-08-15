from flask import Blueprint, render_template, request, jsonify, current_app, send_file
from app.models.database import db_manager
from datetime import datetime, timedelta
import logging
import os
import tempfile
import paramiko
from urllib.parse import quote
import math
import traceback

bp = Blueprint('smb', __name__)

@bp.route('/debug-ping')
def debug_ping():
    return 'smb-ok'



@bp.route('/debug-all-smb')
def debug_all_smb():
    """Отладка всех активных SMB файлов"""
    try:
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    SELECT f.id as file_id, f.path, u.username, s.open_time, s.last_seen
                    FROM active_smb_sessions s
                    JOIN smb_files f ON s.file_id = f.id
                    JOIN smb_users u ON s.user_id = u.id
                    ORDER BY s.last_seen DESC
                    LIMIT 20
                """)
                all_files = cursor.fetchall()
        
        return jsonify({
            'total_active_smb_files': len(all_files),
            'files': [dict(f) for f in all_files]
        })
        
    except Exception as e:
        current_app.logger.error(f"Debug all SMB error: {e}")
        return jsonify({'error': str(e)}), 500

@bp.route('/debug-rdp-filter')
def debug_rdp_filter():
    """Отладка фильтра RDP для SMB файлов"""
    try:
        username = request.args.get('username', 'l.polyakova')
        
        # Получаем SMB файлы пользователя (ищем по нормализованному имени)
        smb_files = []
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                # Ищем файлы, где имя пользователя содержит искомое имя (без учета домена и регистра)
                cursor.execute("""
                    SELECT f.id as file_id, f.path, u.username, s.open_time, s.last_seen
                    FROM active_smb_sessions s
                    JOIN smb_files f ON s.file_id = f.id
                    JOIN smb_users u ON s.user_id = u.id
                    WHERE LOWER(u.username) LIKE %s OR LOWER(u.username) LIKE %s
                    ORDER BY s.open_time DESC
                """, [f'%{username.lower()}%', f'%{username.lower()}'])
                smb_files = cursor.fetchall()
        
        # Получаем RDP сессии пользователя (ищем по нормализованному имени)
        normalized_username = normalize_username_for_comparison(username)
        rdp_sessions = []
        try:
            with db_manager.get_connection('rdp') as rdp_conn:
                with rdp_conn.cursor() as rdp_cursor:
                    # Активные RDP сессии (ищем по LIKE для нормализованного имени)
                    rdp_cursor.execute("""
                        SELECT username, login_time, collection_name, 'active' as type
                        FROM rdp_active_sessions
                        WHERE LOWER(username) LIKE %s
                    """, [f'%{normalized_username}%'])
                    active_rdp = rdp_cursor.fetchall()
                    
                    # История RDP сессий за последние 7 дней
                    rdp_cursor.execute("""
                        SELECT username, login_time, collection_name, 'history' as type
                        FROM rdp_session_history 
                        WHERE LOWER(username) LIKE %s AND login_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                        ORDER BY login_time DESC
                    """, [f'%{normalized_username}%'])
                    history_rdp = rdp_cursor.fetchall()
                    
                    rdp_sessions = list(active_rdp) + list(history_rdp)
        except Exception as e:
            rdp_sessions = [{'error': str(e)}]
        
        # Анализ сопоставления
        analysis = []
        for smb_file in smb_files:
            file_analysis = {
                'file': dict(smb_file),
                'matching_rdp_sessions': [],
                'in_rdp_session': False
            }
            
            if smb_file.get('open_time'):
                smb_username = normalize_username_for_comparison(smb_file['username'])
                for rdp_session in rdp_sessions:
                    rdp_username = normalize_username_for_comparison(rdp_session.get('username', ''))
                    if (rdp_username == smb_username and 
                        rdp_session.get('login_time') and 
                        smb_file['open_time'] >= rdp_session['login_time']):
                        
                        session_end = rdp_session['login_time'] + timedelta(hours=24)
                        if smb_file['open_time'] <= session_end:
                            file_analysis['matching_rdp_sessions'].append(dict(rdp_session))
                            file_analysis['in_rdp_session'] = True
            
            analysis.append(file_analysis)
        
        return jsonify({
            'username': username,
            'smb_files_count': len(smb_files),
            'rdp_sessions_count': len(rdp_sessions),
            'rdp_sessions': [dict(s) for s in rdp_sessions],
            'analysis': analysis
        })
        
    except Exception as e:
        current_app.logger.error(f"Debug RDP filter error: {e}")
        return jsonify({'error': str(e)}), 500

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

def normalize_username_for_comparison(username):
    """Нормализует имя пользователя для сравнения SMB и RDP данных"""
    if not username:
        return ''
    
    # Убираем домен (ANTARES\) если есть
    if '\\' in username:
        username = username.split('\\')[-1]
    
    # Приводим к нижнему регистру
    return username.lower()

def normalize_username(username):
    """Нормализация имени пользователя"""
    if not username:
        return username
    return username.lower().replace('\\', '_').replace('/', '_')

def normalize_path_for_search(term: str) -> str:
    """Нормализация поискового термина пути под колонку norm_path (lower + '/')."""
    if not term:
        return ''
    return term.replace('\\', '/').lower()

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
        # Нормализованные значения для SQL-фильтров
        search_user_norm = normalize_username_for_comparison(search_user) if search_user else ''
        search_file_norm = normalize_path_for_search(search_file) if search_file else ''
        # Фильтры по умолчанию включены, если не передано явно '0'
        filter_modified = request.args.get('filter_modified', '1') != '0'
        filter_rdp_session = request.args.get('filter_rdp_session', '1') != '0'
        # Параметры пагинации
        page = request.args.get('page', type=int) or 1
        per_page = request.args.get('per_page', type=int) or 10
        if page < 1:
            page = 1
        # Ограничим per_page разумными рамками
        per_page = max(5, min(per_page, 100))
        # Всегда используем поиск по истории (а не только активные сессии)
        # Это позволяет находить файлы по поисковым терминам даже без дополнительных фильтров
        search_mode = True
        
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                # Получаем всех пользователей
                users_query = """
                    SELECT u.id, u.username, COUNT(s.user_id) as open_files_count,
                           MAX(s.last_seen) as last_activity
                    FROM smb_users u
                    LEFT JOIN active_smb_sessions s ON u.id = s.user_id
                """
                params = []
                where_conditions = []
                
                if search_user_norm:
                    where_conditions.append("LOWER(u.username) LIKE %s")
                    params.append(f"%{search_user_norm}%")
                
                if where_conditions:
                    users_query += " WHERE " + " AND ".join(where_conditions)
                
                users_query += " GROUP BY u.id, u.username ORDER BY open_files_count DESC, u.username ASC LIMIT 50"
                cursor.execute(users_query, params)
                users = cursor.fetchall()
                
                # Проверяем, есть ли в БД колонка нормализованного пути
                has_norm_path = False
                try:
                    cursor.execute("SHOW COLUMNS FROM smb_files LIKE 'norm_path'")
                    has_norm_path = cursor.fetchone() is not None
                except Exception:
                    has_norm_path = False

                # Поиск по всей истории smb_session_history с использованием встроенных полей БД
                files = []
                
                # Нормализатор имени пользователя на стороне SQL (убираем домен и нижний регистр)
                u_norm = "LOWER(CASE WHEN INSTR(u.username, '\\\\') > 0 THEN SUBSTRING_INDEX(u.username, '\\\\', -1) ELSE u.username END)"
                
                # Строим условия поиска (логика И для всех фильтров)
                where_clauses = []
                params = []
                
                # Поиск по пути файла (если введен)
                if search_file_norm:
                    if has_norm_path:
                        where_clauses.append("f.norm_path LIKE %s")
                    else:
                        where_clauses.append("LOWER(REPLACE(f.path, CHAR(92), '/')) LIKE %s")
                    params.append(f"%{search_file_norm}%")
                
                # Поиск по пользователю (если введен)
                if search_user_norm:
                    where_clauses.append(f"{u_norm} LIKE %s")
                    params.append(f"%{search_user_norm}%")
                
                # Фильтр "Изменён" (если включен)
                if filter_modified:
                    where_clauses.append("(h.final_size != h.initial_size OR h.final_size IS NULL)")
                
                # Фильтр "Внутри RDP" (если включен)
                if filter_rdp_session:
                    where_clauses.append("h.open_in_rdp = 1")
                
                # Формируем WHERE-клаузу
                where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
                base_from = "FROM smb_session_history h JOIN smb_files f ON h.file_id = f.id JOIN smb_users u ON h.user_id = u.id"
                
                # Подсчёт общего количества результатов
                count_sql = f"SELECT COUNT(*) AS total {base_from} {where_sql}"
                cursor.execute(count_sql, params)
                total_files = cursor.fetchone()['total']
                
                # Получение результатов текущей страницы
                select_sql = f"""
                    SELECT 
                        f.id AS file_id,
                        f.path,
                        u.id AS user_id,
                        u.username,
                        h.open_time,
                        h.initial_size,
                        h.open_in_rdp,
                        CASE WHEN (h.final_size != h.initial_size OR h.final_size IS NULL) THEN 1 ELSE 0 END AS is_modified
                    {base_from}
                    {where_sql}
                    ORDER BY h.open_time DESC
                    LIMIT %s OFFSET %s
                """
                
                page_params = list(params) + [per_page, (page - 1) * per_page]
                cursor.execute(select_sql, page_params)
                rows = cursor.fetchall()
                
                # Обрабатываем результаты
                for r in rows:
                    item = dict(r)
                    item['id'] = r['file_id']
                    item['filename'] = os.path.basename(r['path']) if r.get('path') else None
                    item['file_size'] = r.get('initial_size')
                    item['is_modified'] = bool(r.get('is_modified', 0))
                    item['in_rdp_session'] = bool(r.get('open_in_rdp', 0))  # Используем встроенное поле
                    files.append(item)

                # Статистика (выносим ИЗ цикла!)
                cursor.execute("SELECT COUNT(*) as total FROM active_smb_sessions")
                active_sessions = cursor.fetchone()['total']
                cursor.execute("SELECT COUNT(DISTINCT user_id) as total FROM active_smb_sessions")
                active_users = cursor.fetchone()['total']
                cursor.execute("SELECT COUNT(DISTINCT file_id) as total FROM active_smb_sessions")
                open_files = cursor.fetchone()['total']
                cursor.execute("""
                    SELECT COUNT(DISTINCT file_id) as total 
                    FROM smb_session_history 
                    WHERE open_time >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                      AND final_size != initial_size
                """)
                modified_files_today = cursor.fetchone()['total']

                # Пользователи с активными RDP
                users_with_rdp = 0
                try:
                    with db_manager.get_connection('rdp') as rdp_conn:
                        with rdp_conn.cursor() as rdp_cursor:
                            rdp_cursor.execute("SELECT COUNT(DISTINCT username) as total FROM rdp_active_sessions")
                            users_with_rdp = rdp_cursor.fetchone()['total']
                except Exception as e:
                    current_app.logger.warning(f"Could not fetch RDP users count: {e}")
                    users_with_rdp = 0

                return render_template('smb/index.html',
                                     users=users,
                                     files=files,
                                     search_user=search_user,
                                     search_file=search_file,
                                     filter_modified=filter_modified,
                                     filter_rdp_session=filter_rdp_session,
                                     pagination={
                                         'page': page,
                                         'per_page': per_page,
                                         'total': total_files,
                                         'pages': (math.ceil(total_files / per_page) if per_page else 1)
                                     },
                                     stats={
                                              'active_sessions': active_sessions,
                                              'active_users': active_users,
                                              'open_files': open_files,
                                              'modified_files_today': modified_files_today,
                                              'users_with_rdp': users_with_rdp
                                          })
                recent_query = """
                    SELECT DISTINCT f.id as file_id, f.path, u.id as user_id, u.username,
                           s.open_time, s.initial_size, s.last_seen,
                           CASE 
                               WHEN EXISTS (
                                   SELECT 1 FROM smb_session_history h 
                                   WHERE h.file_id = f.id 
                                     AND h.user_id = u.id 
                                     AND h.open_time BETWEEN s.open_time AND s.last_seen
                                     AND (h.final_size != h.initial_size OR h.final_size IS NULL)
                               ) THEN 1
                               ELSE 0
                           END as is_modified
                    FROM active_smb_sessions s
                    JOIN smb_files f ON s.file_id = f.id
                    JOIN smb_users u ON s.user_id = u.id
                """
                recent_params = []
                where_conditions = []
                
                if search_file_norm:
                    if has_norm_path:
                        where_conditions.append("f.norm_path LIKE %s")
                    else:
                        where_conditions.append("LOWER(REPLACE(f.path, CHAR(92), '/')) LIKE %s")
                    recent_params.append(f"%{search_file_norm}%")

                if search_user_norm:
                    where_conditions.append("LOWER(u.username) LIKE %s")
                    recent_params.append(f"%{search_user_norm}%")
                
                if where_conditions:
                    recent_query += " WHERE " + " AND ".join(where_conditions)
                
                recent_query += " ORDER BY s.last_seen DESC LIMIT 500"  # Увеличиваем лимит для фильтрации
                cursor.execute(recent_query, recent_params)
                recent = cursor.fetchall()
                
                # Получаем данные RDP сессий для сопоставления (ограничиваем круг пользователей)
                rdp_sessions = []
                candidate_users = sorted({normalize_username_for_comparison(r['username']) for r in recent if r.get('username')})
                if search_user_norm:
                    candidate_users = sorted(set(candidate_users) | {search_user_norm})
                try:
                    if candidate_users:
                        like_terms = [f"%{u}%" for u in candidate_users]
                        with db_manager.get_connection('rdp') as rdp_conn:
                            with rdp_conn.cursor() as rdp_cursor:
                                active_where = " OR ".join(["LOWER(username) LIKE %s"] * len(like_terms))
                                rdp_cursor.execute(f"""
                                    SELECT username, login_time 
                                    FROM rdp_active_sessions
                                    WHERE {active_where}
                                """, like_terms)
                                active_rdp = rdp_cursor.fetchall()

                                hist_where = " OR ".join(["LOWER(username) LIKE %s"] * len(like_terms))
                                rdp_cursor.execute(f"""
                                    SELECT username, login_time 
                                    FROM rdp_session_history 
                                    WHERE ({hist_where})
                                      AND login_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                                """, like_terms)
                                history_rdp = rdp_cursor.fetchall()

                                rdp_sessions = list(active_rdp) + list(history_rdp)
                    else:
                        rdp_sessions = []
                except Exception as e:
                    current_app.logger.warning(f"Could not fetch RDP sessions: {e}")
                    rdp_sessions = []
                
                # Подготовка структуры, ожидаемой шаблоном с фильтрацией
                files = []
                for r in recent:
                    item = dict(r)
                    item['id'] = r['file_id']
                    item['filename'] = os.path.basename(r['path']) if r.get('path') else None
                    item['file_size'] = r.get('initial_size')
                    item['is_modified'] = bool(r.get('is_modified', 0))
                    
                    # Определяем, был ли файл открыт внутри RDP сессии
                    item['in_rdp_session'] = False
                    if rdp_sessions and r.get('open_time') and r.get('username'):
                        smb_username = normalize_username_for_comparison(r['username'])
                        for rdp_session in rdp_sessions:
                            rdp_username = normalize_username_for_comparison(rdp_session.get('username', ''))
                            if (rdp_username == smb_username and 
                                rdp_session.get('login_time') and r['open_time'] >= rdp_session['login_time']):
                                # Файл открыт после начала RDP сессии
                                # Предполагаем, что RDP сессия длится максимум 24 часа
                                session_end = rdp_session['login_time'] + timedelta(hours=24)
                                if r['open_time'] <= session_end:
                                    item['in_rdp_session'] = True
                                    break
                    
                    # Не считаем файл изменённым автоматически из-за RDP
                    
                    # Применяем фильтры
                    if filter_modified and not item['is_modified']:
                        continue
                    if filter_rdp_session and not item['in_rdp_session']:
                        continue
                    
                    files.append(item)
                
                # Пагинация результатов
                total_files = len(files)
                start = (page - 1) * per_page
                end = start + per_page
                files = files[start:end]
                
                # Статистика
                cursor.execute("SELECT COUNT(*) as total FROM active_smb_sessions")
                active_sessions = cursor.fetchone()['total']
                
                cursor.execute("SELECT COUNT(DISTINCT user_id) as total FROM active_smb_sessions")
                active_users = cursor.fetchone()['total']
                
                cursor.execute("SELECT COUNT(DISTINCT file_id) as total FROM active_smb_sessions")
                open_files = cursor.fetchone()['total']
                
                # Количество файлов, измененных за последние 24 часа
                cursor.execute("""
                    SELECT COUNT(DISTINCT file_id) as total 
                    FROM smb_session_history 
                    WHERE open_time >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                    AND final_size != initial_size
                """)
                modified_files_today = cursor.fetchone()['total']
                
                # Количество пользователей с активными RDP сессиями
                users_with_rdp = 0
                try:
                    with db_manager.get_connection('rdp') as rdp_conn:
                        with rdp_conn.cursor() as rdp_cursor:
                            rdp_cursor.execute("SELECT COUNT(DISTINCT username) as total FROM rdp_active_sessions")
                            users_with_rdp = rdp_cursor.fetchone()['total']
                except Exception as e:
                    current_app.logger.warning(f"Could not fetch RDP users count: {e}")
                    users_with_rdp = 0
                
                return render_template('smb/index.html',
                                     users=users,
                                     files=files,
                                     search_user=search_user,
                                     search_file=search_file,
                                     filter_modified=filter_modified,
                                     filter_rdp_session=filter_rdp_session,
                                     pagination={
                                         'page': page,
                                         'per_page': per_page,
                                         'total': total_files,
                                         'pages': (math.ceil(total_files / per_page) if per_page else 1)
                                     },
                                     stats={
                                          'active_sessions': active_sessions,
                                          'active_users': active_users,
                                          'open_files': open_files,
                                          'modified_files_today': modified_files_today,
                                          'users_with_rdp': users_with_rdp
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
        
        filter_modified = request.args.get('filter_modified') == '1'
        filter_rdp_session = request.args.get('filter_rdp_session') == '1'
        
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                # Получаем базовые данные о сессиях (без фильтров RDP)
                query = """
                    SELECT s.session_id, u.username, f.path, f.id AS file_id, c.host,
                           s.open_time, s.last_seen, s.initial_size, u.id as user_id,
                           CASE 
                               WHEN EXISTS (
                                   SELECT 1 FROM smb_session_history h 
                                   WHERE h.file_id = f.id AND h.user_id = u.id 
                                   AND h.open_time BETWEEN s.open_time AND s.last_seen
                                   AND (h.final_size != h.initial_size OR h.final_size IS NULL)
                               ) THEN 1
                               ELSE 0
                           END as is_modified
                    FROM active_smb_sessions s
                    JOIN smb_users u ON s.user_id = u.id
                    JOIN smb_files f ON s.file_id = f.id
                    JOIN smb_clients c ON s.client_id = c.id
                    ORDER BY s.last_seen DESC
                """
                cursor.execute(query)
                all_sessions = cursor.fetchall()
                
                # Получаем данные RDP сессий для сопоставления
                rdp_sessions = []
                try:
                    with db_manager.get_connection('rdp') as rdp_conn:
                        with rdp_conn.cursor() as rdp_cursor:
                            # Получаем активные RDP сессии
                            rdp_cursor.execute("""
                                SELECT username, login_time 
                                FROM rdp_active_sessions
                            """)
                            active_rdp = rdp_cursor.fetchall()
                            
                            # Получаем историю RDP сессий за последние 7 дней
                            rdp_cursor.execute("""
                                SELECT username, login_time 
                                FROM rdp_session_history 
                                WHERE login_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)
                            """)
                            history_rdp = rdp_cursor.fetchall()
                            
                            rdp_sessions = list(active_rdp) + list(history_rdp)
                except Exception as e:
                    current_app.logger.warning(f"Could not fetch RDP sessions: {e}")
                    rdp_sessions = []
                
                # Применяем фильтры и добавляем флаги RDP
                sessions = []
                for session in all_sessions:
                    session_dict = dict(session)
                    session_dict['is_modified'] = bool(session.get('is_modified', 0))
                    
                    # Определяем, был ли файл открыт внутри RDP сессии
                    session_dict['in_rdp_session'] = False
                    if rdp_sessions and session.get('open_time') and session.get('username'):
                        smb_username = normalize_username_for_comparison(session['username'])
                        for rdp_session in rdp_sessions:
                            rdp_username = normalize_username_for_comparison(rdp_session.get('username', ''))
                            if (rdp_username == smb_username and 
                                rdp_session.get('login_time') and session['open_time'] >= rdp_session['login_time']):
                                # Файл открыт после начала RDP сессии
                                # Предполагаем, что RDP сессия длится максимум 24 часа
                                session_end = rdp_session['login_time'] + timedelta(hours=24)
                                if session['open_time'] <= session_end:
                                    session_dict['in_rdp_session'] = True
                                    break
                    
                    # Не считаем файл изменённым автоматически из-за RDP
                    
                    # Применяем фильтры
                    if filter_modified and not session_dict['is_modified']:
                        continue
                    if filter_rdp_session and not session_dict['in_rdp_session']:
                        continue
                    
                    sessions.append(session_dict)
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

@bp.route('/files-modified')
def files_modified():
    """Статистика изменённых файлов с выбором периода"""
    try:
        days = request.args.get('days', 1, type=int)  # По умолчанию 1 день
        
        # Определяем период
        date_from = datetime.now() - timedelta(days=days)
        
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                # Статистика изменённых файлов за период
                cursor.execute("""
                    SELECT 
                        COUNT(DISTINCT h.file_id) as total_modified_files,
                        COUNT(DISTINCT h.user_id) as total_users,
                        COUNT(*) as total_modifications
                    FROM smb_session_history h
                    WHERE h.open_time >= %s 
                    AND (h.final_size != h.initial_size OR h.final_size IS NULL)
                """, (date_from,))
                stats = cursor.fetchone()
                
                # Топ пользователей по количеству изменений
                cursor.execute("""
                    SELECT 
                        u.username,
                        u.id as user_id,
                        COUNT(DISTINCT h.file_id) as modified_files,
                        COUNT(*) as total_modifications,
                        MAX(h.open_time) as last_activity
                    FROM smb_session_history h
                    JOIN smb_users u ON h.user_id = u.id
                    WHERE h.open_time >= %s 
                    AND (h.final_size != h.initial_size OR h.final_size IS NULL)
                    GROUP BY u.id, u.username
                    ORDER BY total_modifications DESC, modified_files DESC
                    LIMIT 20
                """, (date_from,))
                top_users = cursor.fetchall()
                
                # Последние изменённые файлы
                cursor.execute("""
                    SELECT 
                        f.path,
                        f.id as file_id,
                        u.username,
                        u.id as user_id,
                        h.open_time,
                        h.close_time,
                        h.initial_size,
                        h.final_size,
                        c.host
                    FROM smb_session_history h
                    JOIN smb_files f ON h.file_id = f.id
                    JOIN smb_users u ON h.user_id = u.id
                    LEFT JOIN smb_clients c ON h.client_id = c.id
                    WHERE h.open_time >= %s 
                    AND (h.final_size != h.initial_size OR h.final_size IS NULL)
                    ORDER BY h.open_time DESC
                    LIMIT 50
                """, (date_from,))
                recent_files = cursor.fetchall()
                
                return render_template('smb/files_modified.html',
                                     stats=stats,
                                     top_users=top_users,
                                     recent_files=recent_files,
                                     days=days,
                                     date_from=date_from)
                
    except Exception as e:
        current_app.logger.error(f"SMB files modified error: {e}")
        return f"Ошибка: {e}", 500

@bp.route('/files-rdp-users')
def files_rdp_users():
    """Файлы пользователей с активными RDP сессиями"""
    try:
        # Получаем пользователей с активными RDP сессиями
        rdp_users = []
        try:
            with db_manager.get_connection('rdp') as rdp_conn:
                with rdp_conn.cursor() as rdp_cursor:
                    rdp_cursor.execute("SELECT DISTINCT username FROM rdp_active_sessions")
                    rdp_users = [row['username'] for row in rdp_cursor.fetchall()]
        except Exception as e:
            current_app.logger.warning(f"Could not fetch RDP users: {e}")
            rdp_users = []
        
        if not rdp_users:
            return render_template('smb/open_now_table.html', sessions=[], message="Нет пользователей с активными RDP сессиями")
        
        # Получаем файлы только тех пользователей, у которых есть активные RDP сессии
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cursor:
                # Создаем список нормализованных имен RDP пользователей для сравнения
                normalized_rdp_users = [normalize_username_for_comparison(username) for username in rdp_users]
                
                query = """
                    SELECT s.session_id, u.username, f.path, f.id AS file_id, c.host,
                           s.open_time, s.last_seen, s.initial_size, u.id as user_id,
                           1 as is_modified, 1 as in_rdp_session
                    FROM active_smb_sessions s
                    JOIN smb_users u ON s.user_id = u.id
                    JOIN smb_files f ON s.file_id = f.id
                    JOIN smb_clients c ON s.client_id = c.id
                    ORDER BY s.last_seen DESC
                """
                cursor.execute(query)
                all_sessions = cursor.fetchall()
                
                # Фильтруем только файлы пользователей с активными RDP сессиями
                sessions = []
                for session in all_sessions:
                    session_dict = dict(session)
                    smb_username = normalize_username_for_comparison(session['username'])
                    
                    # Проверяем, есть ли у пользователя активная RDP сессия
                    if smb_username in normalized_rdp_users:
                        sessions.append(session_dict)
                
                return render_template('smb/open_now_table.html', sessions=sessions)
                
    except Exception as e:
        current_app.logger.error(f"SMB files RDP users error: {e}")
        return f"Ошибка: {e}", 500

@bp.route('/user/<int:user_id>')
def user_detail(user_id):
    """Детальная страница пользователя SMB"""
    try:
        page = request.args.get('page', 1, type=int)
        days = request.args.get('days', 7, type=int)
        activity = request.args.get('activity', 'all')  # all, active, history
        filter_modified = request.args.get('filter_modified') == '1'
        filter_rdp_session = request.args.get('filter_rdp_session') == '1'
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
                
                # История сессий с фильтрами
                date_from = datetime.now() - timedelta(days=days)
                history_query = """
                    SELECT f.id AS file_id, f.path, h.open_time, h.close_time, h.initial_size, h.final_size, u.username
                    FROM smb_session_history h
                    JOIN smb_files f ON h.file_id = f.id
                    JOIN smb_users u ON h.user_id = u.id
                    WHERE h.user_id = %s AND h.open_time >= %s
                """
                
                # Добавляем фильтр "изменен" (файл был изменен)
                if filter_modified:
                    history_query += " AND (h.final_size != h.initial_size OR h.final_size IS NULL)"
                
                history_query += " ORDER BY h.open_time DESC LIMIT %s OFFSET %s"
                cursor.execute(history_query, (user_id, date_from, per_page, offset))
                history_sessions = list(cursor.fetchall())
                
                # Применяем фильтр "внутри RDP" если нужно
                if filter_rdp_session and history_sessions:
                    # Получаем RDP сессии пользователя
                    rdp_sessions = []
                    try:
                        with db_manager.get_connection('rdp') as rdp_conn:
                            with rdp_conn.cursor() as rdp_cursor:
                                # Получаем RDP сессии за период
                                normalized_username = normalize_username_for_comparison(user['username'])
                                rdp_cursor.execute("""
                                    SELECT login_time, logout_time, collection_name
                                    FROM rdp_session_history 
                                    WHERE LOWER(username) LIKE %s AND login_time >= %s
                                    ORDER BY login_time DESC
                                """, [f'%{normalized_username}%', date_from])
                                rdp_sessions = list(rdp_cursor.fetchall())
                    except Exception as e:
                        current_app.logger.error(f"Error getting RDP sessions: {e}")
                    
                    # Фильтруем файлы, открытые внутри RDP сессий
                    filtered_sessions = []
                    for session in history_sessions:
                        session_dict = dict(session)
                        session_dict['in_rdp_session'] = False
                        
                        if rdp_sessions and session.get('open_time') and session.get('username'):
                            smb_username = normalize_username_for_comparison(session['username'])
                            for rdp_session in rdp_sessions:
                                rdp_username = normalize_username_for_comparison(user['username'])
                                if (rdp_username == smb_username and 
                                    rdp_session.get('login_time') and 
                                    session['open_time'] >= rdp_session['login_time']):
                                    # Файл открыт после начала RDP сессии
                                    session_end = rdp_session.get('logout_time') or (rdp_session['login_time'] + timedelta(hours=24))
                                    if session['open_time'] <= session_end:
                                        session_dict['in_rdp_session'] = True
                                        break
                        
                        if session_dict['in_rdp_session']:
                            filtered_sessions.append(session_dict)
                    
                    history_sessions = filtered_sessions
                
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
                                     next_num=next_num,
                                     filter_modified=filter_modified,
                                     filter_rdp_session=filter_rdp_session)
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
