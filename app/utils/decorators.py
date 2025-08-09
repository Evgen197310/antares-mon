from functools import wraps
from flask import session, redirect, url_for, flash, request


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('user'):
            flash('Требуется вход в систему', 'warning')
            return redirect(url_for('auth.login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = session.get('user')
        if not user:
            flash('Требуется вход в систему', 'warning')
            return redirect(url_for('auth.login', next=request.path))
        if not user.get('is_admin'):
            flash('Недостаточно прав', 'error')
            return redirect(url_for('main.index'))
        return view(*args, **kwargs)
    return wrapped


def require_section(section_name: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = session.get('user')
            if not user:
                flash('Требуется вход в систему', 'warning')
                return redirect(url_for('auth.login', next=request.path))
            # MVP: администратору всё разрешено, для остальных можно расширить позднее
            if not user.get('is_admin'):
                # TODO: check granular permissions later
                flash('Недостаточно прав для доступа к разделу', 'error')
                return redirect(url_for('main.index'))
            return view(*args, **kwargs)
        return wrapped
    return decorator
