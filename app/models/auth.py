import hashlib
import hmac
from datetime import datetime
from typing import Optional, Dict
from app.models.database import db_manager

PWD_ALGO = 'pbkdf2_sha256'
ITERATIONS = 260000
SALT = b'antares-monitoring-salt'  # static salt; can be replaced with per-user salts later


def _hash_password(password: str) -> str:
    pwd = password.encode('utf-8')
    dk = hashlib.pbkdf2_hmac('sha256', pwd, SALT, ITERATIONS)
    return f"{PWD_ALGO}${ITERATIONS}$" + dk.hex()


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, iter_s, hexhash = password_hash.split('$', 2)
        if algo != PWD_ALGO:
            return False
        iters = int(iter_s)
        dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), SALT, iters)
        return hmac.compare_digest(dk.hex(), hexhash)
    except Exception:
        return False


def ensure_tables():
    """Create users table if not exists in 'monitoring' DB."""
    with db_manager.get_connection('monitoring') as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                  id INT PRIMARY KEY AUTO_INCREMENT,
                  username VARCHAR(100) UNIQUE NOT NULL,
                  password_hash VARCHAR(255) NOT NULL,
                  is_admin TINYINT(1) NOT NULL DEFAULT 0,
                  active TINYINT(1) NOT NULL DEFAULT 1,
                  created_at DATETIME NOT NULL,
                  last_login DATETIME NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )


def get_user_by_username(username: str) -> Optional[Dict]:
    with db_manager.get_connection('monitoring') as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE username=%s", (username,))
            return cur.fetchone()


def get_user_by_id(user_id: int) -> Optional[Dict]:
    with db_manager.get_connection('monitoring') as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id=%s", (user_id,))
            return cur.fetchone()


def list_users() -> list:
    with db_manager.get_connection('monitoring') as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, is_admin, active, created_at, last_login FROM users ORDER BY username")
            return cur.fetchall()


def create_user(username: str, password: str, is_admin: bool = False) -> int:
    now = datetime.now()
    ph = _hash_password(password)
    with db_manager.get_connection('monitoring') as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password_hash, is_admin, active, created_at) VALUES (%s,%s,%s,%s,%s)",
                (username, ph, 1 if is_admin else 0, 1, now)
            )
            return cur.lastrowid


def set_admin(user_id: int, is_admin: bool):
    with db_manager.get_connection('monitoring') as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET is_admin=%s WHERE id=%s", (1 if is_admin else 0, user_id))


def set_active(user_id: int, active: bool):
    with db_manager.get_connection('monitoring') as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET active=%s WHERE id=%s", (1 if active else 0, user_id))


def update_password(user_id: int, new_password: str):
    ph = _hash_password(new_password)
    with db_manager.get_connection('monitoring') as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET password_hash=%s WHERE id=%s", (ph, user_id))


def verify_credentials(username: str, password: str) -> Optional[Dict]:
    u = get_user_by_username(username)
    if not u or not u.get('active'):
        return None
    if _verify_password(password, u['password_hash']):
        with db_manager.get_connection('monitoring') as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET last_login=%s WHERE id=%s", (datetime.now(), u['id']))
        return u
    return None
