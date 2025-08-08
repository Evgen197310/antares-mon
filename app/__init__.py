from flask import Flask
from datetime import datetime
from app.config import Config
from app.models.database import init_db

def create_app(config_class=Config):
    """Factory для создания Flask приложения"""
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    # Инициализация БД
    init_db(app)
    
    # Регистрация blueprints
    from app.blueprints.main import bp as main_bp
    from app.blueprints.vpn import bp as vpn_bp
    from app.blueprints.rdp import bp as rdp_bp
    from app.blueprints.smb import bp as smb_bp
    from app.blueprints.api import bp as api_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(vpn_bp, url_prefix='/vpn')
    app.register_blueprint(rdp_bp, url_prefix='/rdp')
    app.register_blueprint(smb_bp, url_prefix='/smb')
    app.register_blueprint(api_bp, url_prefix='/api')
    
    # Регистрация фильтров Jinja2
    from app.utils.filters import register_filters
    register_filters(app)
    
    # Контекстный процессор для глобальных переменных шаблонов
    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}
    
    return app
