from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from app.models.auth import verify_credentials

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    next_url = request.args.get('next') or request.form.get('next') or url_for('main.index')
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = verify_credentials(username, password)
        if user:
            session['user'] = {
                'id': user['id'],
                'username': user['username'],
                'is_admin': bool(user['is_admin'])
            }
            flash('Добро пожаловать!', 'success')
            return redirect(next_url)
        flash('Неверный логин или пароль', 'error')
    return render_template('auth/login.html', next_url=next_url)


@bp.route('/logout')
def logout():
    session.pop('user', None)
    flash('Вы вышли из системы', 'success')
    return redirect(url_for('auth.login'))
