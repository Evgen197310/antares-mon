import json
import os

class Config:
    """Конфигурация приложения мониторинга"""
    
    def __init__(self):
        config_path = os.environ.get('CONFIG_PATH', '/etc/infra/config.json')
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        except FileNotFoundError:
            # Fallback для разработки
            self.config = self._get_default_config()
    
    def _get_default_config(self):
        """Конфигурация по умолчанию для разработки"""
        return {
            "mysql": {
                "vpnstat": {
                    "host": "127.0.0.1",
                    "user": "vpnstat",
                    "password": "password",
                    "database": "vpnstat",
                    "charset": "utf8mb4"
                },
                "rdpstat": {
                    "host": "127.0.0.1",
                    "user": "vpnstat",
                    "password": "password",
                    "database": "rdpstat",
                    "charset": "utf8mb4"
                },
                "smbstat": {
                    "host": "127.0.0.1",
                    "user": "smbstat",
                    "password": "password",
                    "database": "smbstat",
                    "charset": "utf8mb4"
                }
            },
            "paths": {
                "ikev2_state_file": "/var/log/mikrotik/ikev2_active.csv",
                "mikrotik_map": "/opt/monitoring-web/data/full_map.csv"
            }
        }
    
    # MySQL настройки
    @property
    def MYSQL_VPNSTAT(self):
        return self.config['mysql']['vpnstat']
    
    @property
    def MYSQL_RDPSTAT(self):
        return self.config['mysql']['rdpstat']
    
    @property
    def MYSQL_SMBSTAT(self):
        return self.config['mysql']['smbstat']
    
    # Пути и настройки
    @property
    def PATHS(self):
        return self.config.get('paths', {})
    
    @property
    def REMOTE_HOSTS(self):
        return self.config.get('remote_hosts', {})
    
    # Flask настройки
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    HOST = os.environ.get('FLASK_HOST', '0.0.0.0')
    PORT = int(os.environ.get('FLASK_PORT', 8080))
