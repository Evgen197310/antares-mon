from typing import List, Dict, Optional, Tuple, Set
from datetime import datetime
import re
from app.models.database import db_manager

READONLY_SQL = re.compile(r"^\s*(SELECT|SHOW|DESCRIBE|EXPLAIN)\b", re.IGNORECASE)


def ensure_ai_tables():
    """Create audit table for AI queries in 'monitoring' DB."""
    with db_manager.get_connection('monitoring') as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_query_audit (
                  id INT PRIMARY KEY AUTO_INCREMENT,
                  created_at DATETIME NOT NULL,
                  username VARCHAR(100) NOT NULL,
                  db_name VARCHAR(50) NOT NULL,
                  nl_query TEXT NOT NULL,
                  generated_sql TEXT,
                  success TINYINT(1) NOT NULL,
                  error TEXT,
                  rows_returned INT DEFAULT 0
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
            # Manual alias table: username -> aliases (comma-separated)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS user_aliases (
                  id INT PRIMARY KEY AUTO_INCREMENT,
                  username VARCHAR(100) NOT NULL,
                  alias VARCHAR(200) NOT NULL,
                  UNIQUE KEY u_alias (username, alias)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )


def list_databases() -> List[str]:
    # Allowed queryable DBs
    return ['vpnstat', 'rdpstat', 'smbstat']


def _collect_usernames_from_db(db_type: str, candidates: List[Tuple[str, str]]) -> Set[str]:
    """Try to collect distinct usernames from given (table, column) pairs.
    Returns a set of usernames (as-is)."""
    found: Set[str] = set()
    with db_manager.get_connection(db_type) as conn:
        with conn.cursor() as cur:
            for table, col in candidates:
                try:
                    cur.execute(f"SELECT DISTINCT `{col}` AS u FROM `{table}` WHERE `{col}` IS NOT NULL AND `{col}` <> '' LIMIT 20000")
                    rows = cur.fetchall()
                    for r in rows:
                        val = r.get('u')
                        if isinstance(val, str):
                            found.add(val.strip())
                except Exception:
                    continue
    return found


def collect_known_usernames() -> Set[str]:
    """Collect usernames from vpnstat/rdpstat/smbstat using known schemas."""
    usernames: Set[str] = set()
    # vpnstat
    usernames |= _collect_usernames_from_db('vpnstat', [
        ('session_history', 'username'),
        ('session_history', 'user'),
    ])
    # rdpstat
    usernames |= _collect_usernames_from_db('rdpstat', [
        ('rdp_active_sessions', 'username'),
        ('rdp_session_history', 'username'),
        ('session_history', 'username'),
    ])
    # smbstat
    usernames |= _collect_usernames_from_db('smbstat', [
        ('active_smb_sessions', 'username'),
        ('active_smb_sessions', 'user'),
        ('smb_session_history', 'username'),
    ])
    # normalize simple spaces
    return {u for u in usernames if u}


def _username_to_surname(u: str) -> Optional[str]:
    """Heuristic: for logins like e.pustoshilov return 'пустошилов'."""
    if not u or '.' not in u:
        return None
    try:
        surname = u.split('.', 1)[1]
        return surname.lower()
    except Exception:
        return None


def build_alias_map() -> Dict[str, Set[str]]:
    """Return mapping: surname_lower -> set(usernames). Includes manual aliases from monitoring.user_aliases."""
    surn_map: Dict[str, Set[str]] = {}
    # from DB usernames
    for u in collect_known_usernames():
        s = _username_to_surname(u)
        if s:
            surn_map.setdefault(s, set()).add(u)
    # manual aliases
    try:
        with db_manager.get_connection('monitoring') as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT username, alias FROM user_aliases")
                for row in cur.fetchall():
                    alias = (row.get('alias') or '').strip().lower()
                    username = (row.get('username') or '').strip()
                    if alias and username:
                        surn_map.setdefault(alias, set()).add(username)
    except Exception:
        pass
    return surn_map


def enhance_nl_with_aliases(nl_query: str, alias_map: Dict[str, Set[str]]) -> str:
    """Replace standalone surnames in the query with the most relevant username if unique.
    Example: 'Пустошилов' -> 'e.pustoshilov'."""
    if not nl_query:
        return nl_query
    text = nl_query
    # simple token scan; Russian letters
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё._-]+", text)
    replacements: Dict[str, str] = {}
    for t in tokens:
        key = t.lower()
        if key in alias_map and len(alias_map[key]) == 1:
            replacements[t] = list(alias_map[key])[0]
    # apply replacements preserving other text
    for old, new in replacements.items():
        text = re.sub(rf"\b{re.escape(old)}\b", new, text)
    return text


def introspect_schema(db_type: str) -> Dict[str, List[Dict[str, str]]]:
    """Return tables and columns for prompt building."""
    with db_manager.get_connection(db_type) as conn:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            rows = cur.fetchall()
            # PyMySQL DictCursor returns dicts like {'Tables_in_dbname': 'table'}; get the first value
            tables = [list(r.values())[0] for r in rows]
    schema = {}
    with db_manager.get_connection(db_type) as conn:
        with conn.cursor() as cur:
            for t in tables:
                try:
                    cur.execute(f"SHOW COLUMNS FROM `{t}`")
                    cols = cur.fetchall()
                    schema[t] = [{
                        'Field': c.get('Field'),
                        'Type': c.get('Type')
                    } for c in cols]
                except Exception:
                    continue
    return schema


def is_safe_sql(sql: str) -> bool:
    if not READONLY_SQL.match(sql or ''):
        return False
    # single statement only
    if ';' in sql.strip().rstrip(';'):
        return False
    return True


def execute_sql_readonly(db_type: str, sql: str, row_limit: int = 500) -> Tuple[List[Dict], List[str]]:
    """Execute safe readonly SQL and return rows and columns."""
    if not is_safe_sql(sql):
        raise ValueError('Only readonly single SELECT/SHOW/DESCRIBE/EXPLAIN statements are allowed')
    limited_sql = sql
    if READONLY_SQL.match(sql) and 'limit' not in sql.lower():
        limited_sql = sql.rstrip(';') + f' LIMIT {row_limit}'
    with db_manager.get_connection(db_type) as conn:
        with conn.cursor() as cur:
            cur.execute(limited_sql)
            rows = cur.fetchall()
            columns = [desc[0] for desc in (cur.description or [])]
            return rows, columns


def audit_query(username: str, db_name: str, nl_query: str, generated_sql: Optional[str], success: bool, error: Optional[str], rows_returned: int):
    with db_manager.get_connection('monitoring') as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ai_query_audit (created_at, username, db_name, nl_query, generated_sql, success, error, rows_returned) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (datetime.now(), username, db_name, nl_query, generated_sql, 1 if success else 0, error, rows_returned)
            )
