from flask import Blueprint, render_template, current_app
from app.models.database import db_manager
import logging
from datetime import datetime
import os
import subprocess
from app.blueprints.api import _get_version_info

logger = logging.getLogger(__name__)

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    """Главный дашборд системы мониторинга"""
    stats = {
        'vpn_active': 0,
        'vpn_total_today': 0,
        'rdp_active': 0,
        'rdp_total_today': 0,
        'smb_active': 0,
        'smb_users_active': 0
    }
    # Списки для UI
    vpn_users = []            # [{username}]
    rdp_users = []            # [{username, collection_name}]
    smb_files = []            # [{id, name, full_path}]
    
    try:
        # VPN статистика
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cur:
                # Активные VPN сессии (из CSV файла, как в исходном проекте)
                try:
                    # Импортируем утилиту чтения сессий из VPN blueprint, чтобы не дублировать
                    from app.blueprints.vpn import read_active_vpn_sessions
                    sessions = read_active_vpn_sessions() or []
                    stats['vpn_active'] = len(sessions)
                    # Список текущих пользователей (уникальные, сортируем алфавитно, ограничим 10)
                    usernames = sorted({(s.get('username') or '').strip() for s in sessions if s.get('username')})
                    vpn_users = [{'username': u} for u in usernames[:10]]
                except Exception as e:
                    logger.error(f"Error reading VPN state file: {e}")
                    stats['vpn_active'] = 0
                
                # Всего сессий за сегодня
                cur.execute("""
                    SELECT COUNT(*) as count 
                    FROM session_history 
                    WHERE DATE(time_start) = CURDATE()
                """)
                result = cur.fetchone()
                if result:
                    stats['vpn_total_today'] = result['count']
    
    except Exception as e:
        logger.error(f"Ошибка получения VPN статистики: {e}")
    
    try:
        # RDP статистика
        with db_manager.get_connection('rdp') as conn:
            with conn.cursor() as cur:
                # Активные RDP сессии
                cur.execute("""
                    SELECT username, collection_name
                    FROM rdp_active_sessions
                    ORDER BY username ASC
                """)
                rows = cur.fetchall() or []
                stats['rdp_active'] = len(rows)
                # Список пользователей с коллекцией
                seen = set()
                for r in rows:
                    u = (r.get('username') or '').strip()
                    if not u or u in seen:
                        continue
                    rdp_users.append({'username': u, 'collection_name': r.get('collection_name')})
                    seen.add(u)
                    if len(rdp_users) >= 10:
                        break
                
                # Всего сессий за сегодня
                cur.execute("""
                    SELECT COUNT(*) as count 
                    FROM rdp_session_history 
                    WHERE DATE(login_time) = CURDATE()
                """)
                result = cur.fetchone()
                if result:
                    stats['rdp_total_today'] = result['count']
    
    except Exception as e:
        logger.error(f"Ошибка получения RDP статистики: {e}")
    
    try:
        # SMB статистика
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cur:
                # Активные SMB сессии
                cur.execute("SELECT COUNT(*) as count FROM active_smb_sessions")
                result = cur.fetchone()
                if result:
                    stats['smb_active'] = result['count']
                
                # Уникальные активные пользователи
                cur.execute("""
                    SELECT COUNT(DISTINCT user_id) as count 
                    FROM active_smb_sessions
                """)
                result = cur.fetchone()
                if result:
                    stats['smb_users_active'] = result['count']

                # Текущие открытые файлы (имя для показа + полный путь во всплывающей подсказке)
                cur.execute(
                    """
                    SELECT f.id, f.path
                    FROM active_smb_sessions s
                    LEFT JOIN smb_files f ON s.file_id = f.id
                    WHERE f.id IS NOT NULL
                    ORDER BY f.path
                    LIMIT 10
                    """
                )
                for row in cur.fetchall() or []:
                    path = row.get('path') or ''
                    # преобразуем двойные подчёркивания в разделители, берём только имя для показа
                    display = (path or '').replace('__', '\\').replace('/', '\\').split('\\')[-1]
                    # привести регистр: первая буква заглавная, остальное маленькое; расширение нижним регистром
                    base, ext = (display.rsplit('.', 1) + [''])[:2]
                    base = (base.strip().lower().capitalize()) if base else ''
                    ext = ('.' + ext.lower()) if ext else ''
                    smb_files.append({'id': row['id'], 'name': base + ext, 'full_path': path})
    
    except Exception as e:
        logger.error(f"Ошибка получения SMB статистики: {e}")
    
    # Версия приложения для немедленного отображения на странице
    try:
        app_version, _lv = _get_version_info()
    except Exception:
        app_version = 'unknown'

    return render_template('index.html', stats=stats,
                            vpn_users=vpn_users,
                            rdp_users=rdp_users,
                            smb_files=smb_files,
                            app_version=app_version)

@bp.route('/health')
def health_check():
    """Health check для мониторинга состояния приложения"""
    health = {
        'status': 'ok',
        'databases': {},
        'server_time': datetime.now().isoformat(),
    }
    
    # Проверка подключений к БД через db_manager
    db_map = {
        'vpnstat': 'vpn',
        'rdpstat': 'rdp',
        'smbstat': 'smb',
    }
    for label, key in db_map.items():
        try:
            with db_manager.get_connection(key) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            health['databases'][label] = 'ok'
        except Exception as e:
            health['databases'][label] = f'error: {str(e)}'
            health['status'] = 'degraded'
    # Версия, аптайм и корректное last_update (mtime файла VERSION)
    try:
        # uptime
        started = current_app.config.get('STARTED_AT')
        uptime_seconds = int((datetime.now() - started).total_seconds()) if started else 0
        health['uptime_seconds'] = uptime_seconds

        # Версия и время последнего обновления из VERSION
        version, last_update = _get_version_info()
        health['version'] = version
        health['last_update'] = last_update
    except Exception:
        # Не роняем health, просто не добавляем версионную информацию
        pass
    return health
