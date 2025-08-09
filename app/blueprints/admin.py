from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.utils.decorators import admin_required
from app.models.auth import list_users, create_user, set_admin, set_active, update_password

bp = Blueprint('admin', __name__)


@bp.route('/')
@admin_required
def index():
    users = list_users()
    return render_template('admin/users.html', users=users)


@bp.route('/users/new', methods=['POST'])
@admin_required
def users_new():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    if not username or not password:
        flash('Укажите логин и пароль', 'error')
        return redirect(url_for('admin.index'))
    try:
        create_user(username, password, is_admin=False)
        flash('Пользователь создан', 'success')
    except Exception as e:
        flash(f'Ошибка создания пользователя: {e}', 'error')
    return redirect(url_for('admin.index'))


@bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@admin_required
def users_toggle_admin(user_id):
    make_admin = request.form.get('is_admin') == '1'
    set_admin(user_id, make_admin)
    flash('Права обновлены', 'success')
    return redirect(url_for('admin.index'))


@bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@admin_required
def users_toggle_active(user_id):
    active = request.form.get('active') == '1'
    set_active(user_id, active)
    flash('Статус пользователя обновлён', 'success')
    return redirect(url_for('admin.index'))


@bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def users_reset_password(user_id):
    password = request.form.get('password', '').strip()
    if not password:
        flash('Укажите новый пароль', 'error')
        return redirect(url_for('admin.index'))
    update_password(user_id, password)
    flash('Пароль обновлён', 'success')
    return redirect(url_for('admin.index'))
