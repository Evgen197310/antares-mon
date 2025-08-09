from flask import Flask
from datetime import datetime
from app.config import Config
from app.models.database import init_db

def create_app(config_class=Config):
    """Factory для создания Flask приложения"""
    app = Flask(__name__)
    # Загружаем базовые настройки из класса
    app.config.from_object(config_class)
    # Инициализируем экземпляр конфигурации для доступа к динамическим данным (JSON)
    try:
        cfg_instance = config_class()
        # Прокидываем настройки SSH для SMB в Flask config
        app.config['SMB_SSH'] = cfg_instance.SMB_SSH
        # Прокидываем legacy-карту remote_host (используется в старом проекте)
        app.config['REMOTE_HOST'] = cfg_instance.REMOTE_HOST
    except Exception:
        # Без критического падения, в логах будет видно отсутствие SSH настроек
        pass
    # Сохраняем время старта приложения для uptime
    app.config['STARTED_AT'] = datetime.now()
    # Авто‑перезагрузка шаблонов (полезно при правках UI)
    try:
        import os
        auto_reload = os.environ.get('FLASK_TEMPLATES_AUTO_RELOAD', '1') in ('1', 'true', 'True')
    except Exception:
        auto_reload = True
    app.config['TEMPLATES_AUTO_RELOAD'] = auto_reload
    # Отключаем кэш шаблонов и уменьшаем кэш статики
    app.jinja_env.auto_reload = True
    app.jinja_env.cache = {}
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    
    # Инициализация БД
    init_db(app)
    
    # Регистрация blueprints
    from app.blueprints.main import bp as main_bp
    from app.blueprints.vpn import bp as vpn_bp
    from app.blueprints.rdp import bp as rdp_bp
    from app.blueprints.smb import bp as smb_bp
    from app.blueprints.api import bp as api_bp
    from app.blueprints.ai import bp as ai_bp
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.admin import bp as admin_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(vpn_bp, url_prefix='/vpn')
    app.register_blueprint(rdp_bp, url_prefix='/rdp')
    app.register_blueprint(smb_bp, url_prefix='/smb')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(ai_bp, url_prefix='/ai')
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    
    # Регистрация фильтров Jinja2
    from app.utils.filters import register_filters
    register_filters(app)
    
    # Контекстный процессор для глобальных переменных шаблонов
    @app.context_processor
    def inject_now():
        # Пробрасываем информацию о пользователе из сессии (если есть)
        from flask import session
        user = session.get('user')
        return {'now': datetime.now(), 'current_user': user}

    # Требовать аутентификацию для основных разделов
    @app.before_request
    def _require_login_for_sections():
        from flask import request, redirect, url_for, flash, session
        path = request.path or '/'
        # public whitelist
        public = set([
            '/', '/auth/login', '/auth/logout', '/api/health', '/api/status', '/api/docs'
        ])
        if path in public or path.startswith('/static/'):
            return None
        protected_prefixes = ('/vpn', '/rdp', '/smb', '/api')
        if path.startswith(protected_prefixes):
            user = session.get('user')
            if not user:
                flash('Требуется вход в систему', 'warning')
                return redirect(url_for('auth.login', next=path))
        return None

    # Инициализация таблиц аутентификации и создание админа по умолчанию
    try:
        from app.models.auth import ensure_tables, get_user_by_username, create_user
        from app.models.ai_query import ensure_ai_tables
        ensure_tables()
        ensure_ai_tables()
        admin_defaults = cfg_instance.ADMIN_DEFAULT if 'cfg_instance' in locals() else None
        if admin_defaults and admin_defaults.get('username') and admin_defaults.get('password'):
            if not get_user_by_username(admin_defaults['username']):
                create_user(admin_defaults['username'], admin_defaults['password'], is_admin=True)
    except Exception:
        # Не валим приложение, если нет доступа к БД на старте
        pass
    
    return app
