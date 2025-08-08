from flask import Blueprint, render_template, current_app
from app.models.database import db_manager
import logging

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
    
    try:
        # VPN статистика
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cur:
                # Активные VPN сессии (из CSV файла, как в исходном проекте)
                try:
                    state_file = '/var/log/mikrotik/ikev2_active.csv'
                    with open(state_file, 'r', encoding='utf-8') as f:
                        stats['vpn_active'] = sum(1 for line in f if line.strip())
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
                cur.execute("SELECT COUNT(*) as count FROM rdp_active_sessions")
                result = cur.fetchone()
                if result:
                    stats['rdp_active'] = result['count']
                
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
    
    except Exception as e:
        logger.error(f"Ошибка получения SMB статистики: {e}")
    
    return render_template('index.html', stats=stats)

@bp.route('/health')
def health_check():
    """Health check для мониторинга состояния приложения"""
    health = {
        'status': 'ok',
        'databases': {}
    }
    
    # Проверка подключений к БД
    for db_name in ['vpnstat', 'rdpstat', 'smbstat']:
        try:
            if db_name == 'vpnstat':
                with get_vpn_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
            elif db_name == 'rdpstat':
                with get_rdp_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
            elif db_name == 'smbstat':
                with get_smb_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
            
            health['databases'][db_name] = 'ok'
        except Exception as e:
            health['databases'][db_name] = f'error: {str(e)}'
            health['status'] = 'degraded'
    
    return health
