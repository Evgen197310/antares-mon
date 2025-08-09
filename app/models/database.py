import pymysql
from contextlib import contextmanager
from flask import current_app, g
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    """Менеджер подключений к базам данных"""
    
    def __init__(self, app=None):
        self.app = app
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Инициализация с Flask приложением"""
        app.teardown_appcontext(self.close_db)
    
    @contextmanager
    def get_connection(self, db_type):
        """
        Контекстный менеджер для подключений к БД
        
        Args:
            db_type: тип БД ('vpnstat', 'rdpstat', 'smbstat', 'monitoring' и др.)
        """
        # Маппинг имен БД для совместимости
        db_mapping = {
            'vpn': 'vpnstat',
            'rdp': 'rdpstat', 
            'smb': 'smbstat',
            'auth': 'monitoring',
            'monitoring': 'monitoring'
        }
        
        # Получаем правильное имя БД
        actual_db_type = db_mapping.get(db_type, db_type)
        
        # Получаем конфигурацию БД из экземпляра Config
        from app.config import Config
        config_instance = Config()
        
        config_attr = f'MYSQL_{actual_db_type.upper()}'
        if hasattr(config_instance, config_attr):
            config = getattr(config_instance, config_attr)
        else:
            raise ValueError(f"Конфигурация для {db_type} не найдена")
        
        try:
            conn = pymysql.connect(
                host=config['host'],
                user=config['user'],
                password=config['password'],
                database=config['database'],
                charset=config.get('charset', 'utf8mb4'),
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True
            )
            logger.debug(f"Подключение к {db_type} установлено")
            yield conn
        except Exception as e:
            logger.error(f"Ошибка подключения к {db_type}: {e}")
            raise
        finally:
            if 'conn' in locals():
                conn.close()
                logger.debug(f"Подключение к {db_type} закрыто")
    
    def close_db(self, error):
        """Закрытие подключений при завершении контекста"""
        if hasattr(g, 'db_connections'):
            for conn in g.db_connections.values():
                if conn:
                    conn.close()

# Глобальный экземпляр менеджера БД
db_manager = DatabaseManager()

def init_db(app):
    """Инициализация системы БД"""
    db_manager.init_app(app)

# Вспомогательные функции для быстрого доступа
def get_vpn_connection():
    """Получить подключение к vpnstat"""
    return db_manager.get_connection('vpnstat')

def get_rdp_connection():
    """Получить подключение к rdpstat"""
    return db_manager.get_connection('rdpstat')

def get_smb_connection():
    """Получить подключение к smbstat"""
    return db_manager.get_connection('smbstat')
