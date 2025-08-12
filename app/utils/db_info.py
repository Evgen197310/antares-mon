"""Утилиты для получения информации о базах данных"""

from app.models.database import db_manager
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def get_db_start_date():
    """Получает дату начала наполнения БД (самая ранняя запись)"""
    earliest_dates = []
    
    # VPN БД
    try:
        with db_manager.get_connection('vpn') as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MIN(login_time) as earliest FROM session_history WHERE login_time IS NOT NULL")
                result = cur.fetchone()
                if result and result['earliest']:
                    earliest_dates.append(result['earliest'])
                    logger.debug(f"VPN earliest date: {result['earliest']}")
    except Exception as e:
        logger.debug(f"Could not get VPN earliest date: {e}")
    
    # RDP БД
    try:
        with db_manager.get_connection('rdp') as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MIN(login_time) as earliest FROM rdp_session_history WHERE login_time IS NOT NULL")
                result = cur.fetchone()
                if result and result['earliest']:
                    earliest_dates.append(result['earliest'])
                    logger.debug(f"RDP earliest date: {result['earliest']}")
    except Exception as e:
        logger.debug(f"Could not get RDP earliest date: {e}")
    
    # SMB БД
    try:
        with db_manager.get_connection('smb') as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT MIN(open_time) as earliest FROM smb_session_history WHERE open_time IS NOT NULL")
                result = cur.fetchone()
                if result and result['earliest']:
                    earliest_dates.append(result['earliest'])
                    logger.debug(f"SMB earliest date: {result['earliest']}")
    except Exception as e:
        logger.debug(f"Could not get SMB earliest date: {e}")
    
    # Находим самую раннюю дату
    if earliest_dates:
        earliest_date = min(earliest_dates)
        db_start_date = earliest_date.strftime('%d.%m.%Y')
        logger.debug(f"DB start date found: {db_start_date}")
        return db_start_date
    else:
        logger.debug("No earliest dates found in any database")
        return None
