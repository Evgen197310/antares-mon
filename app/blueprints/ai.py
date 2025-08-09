from flask import Blueprint, render_template, request, flash, session
from app.utils.decorators import admin_required
from app.models.ai_query import (
    ensure_ai_tables,
    list_databases,
    introspect_schema,
    execute_sql_readonly,
    audit_query,
    is_safe_sql,
    collect_known_usernames,
    build_alias_map,
    enhance_nl_with_aliases,
)
from app.config import Config
import requests
import re

bp = Blueprint('ai', __name__)

SQL_BLOCK_RE = re.compile(r"```(?:sql)?\n(.*?)```", re.DOTALL | re.IGNORECASE)


def _extract_sql(text: str) -> str:
    if not text:
        return ''
    m = SQL_BLOCK_RE.search(text)
    if m:
        return m.group(1).strip()
    return text.strip()


def _openai_generate_sql(nl_query: str, db_name: str, schema: dict, usernames: list, alias_map: dict) -> str:
    cfg = Config()
    api_key = cfg.OPENAI_API_KEY
    if not api_key:
        raise RuntimeError('OpenAI API ключ не настроен (openai_api_key)')

    system = (
        "You are a senior SQL assistant for MySQL. Generate a single read-only query. "
        "Rules: one statement; strictly read-only (SELECT/SHOW/DESCRIBE/EXPLAIN); use existing columns; add LIMIT if missing; return only SQL fenced code. "
        "If a person surname in Cyrillic is mentioned (e.g., 'Пустошилов'), resolve it to the corresponding username from the provided lists. "
        "If multiple usernames match a surname, use WHERE username IN (...)."
    )
    schema_lines = []
    for t, cols in schema.items():
        defs = ", ".join([f"{c['Field']} {c['Type']}" for c in cols if c.get('Field')])
        schema_lines.append(f"{t}({defs})")
    # Build hints for usernames and surname aliases
    usernames_str = ", ".join(sorted(usernames))
    alias_lines = []
    for k, vals in alias_map.items():
        alias_lines.append(f"{k} -> {', '.join(sorted(vals))}")
    alias_str = "; ".join(alias_lines)

    user = (
        f"Database: {db_name}. Tables: " + "; ".join(schema_lines) + "\n" +
        f"Known usernames (logins): {usernames_str}\n" +
        (f"Surname->username hints: {alias_str}\n" if alias_str else "") +
        f"Task: {nl_query}\nReturn only one SQL statement in a fenced code block. Add a LIMIT if missing."
    )

    # OpenAI Chat Completions v1
    resp = requests.post(
        'https://api.openai.com/v1/chat/completions',
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        },
        json={
            'model': 'gpt-4o-mini',
            'messages': [
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
            'temperature': 0.2,
        },
        timeout=30
    )
    resp.raise_for_status()
    data = resp.json()
    content = data['choices'][0]['message']['content']
    sql = _extract_sql(content)
    return sql


def _detect_candidate_dbs(nl_pre: str) -> list:
    """Heuristics to pick DBs based on NL query keywords. Defaults to all when uncertain."""
    text = (nl_pre or '').lower()
    candidates = set()
    if any(k in text for k in ['rdp', 'терминал', 'удалён', 'удален', 'remote desktop']):
        candidates.add('rdpstat')
    if any(k in text for k in ['vpn', 'ikev2', 'ike2', 'л2тп', 'l2tp']):
        candidates.add('vpnstat')
    if any(k in text for k in ['smb', 'файл', 'шар', 'общ', 'cifs', 'share']):
        candidates.add('smbstat')
    if not candidates:
        candidates = {'vpnstat', 'rdpstat', 'smbstat'}
    return sorted(candidates)


def _summarize_rows(db_name: str, rows: list, columns: list) -> str:
    """Produce a short natural-language summary per DB."""
    if not rows:
        return f"{db_name}: данных нет."
    count = len(rows)
    time_cols = [c for c in (columns or []) if 'time' in c.lower() or 'date' in c.lower() or 'login' in c.lower()]
    time_info = ''
    try:
        if time_cols:
            first_col = time_cols[0]
            vals = [r.get(first_col) for r in rows if r.get(first_col) is not None]
            vals_str = ', '.join(str(v) for v in vals[:3])
            time_info = f", пример времени ({first_col}): {vals_str}"
    except Exception:
        pass
    return f"{db_name}: {count} строк{time_info}"


def _fallback_activity_query(db_name: str, usernames: list, days: int = 7, limit: int = 100):
    """Generic fallback: scan tables having a username-like column and time-like column,
    then fetch recent rows for the usernames.

    Returns tuple (rows, columns, debug_sql) or ([], [], reason).
    """
    try:
        schema = introspect_schema(db_name)
        uname_cols = {'username', 'user', 'login', 'account'}
        time_keywords = ['time', 'date', 'open', 'start', 'login']
        pick_cols_keywords = ['path', 'file', 'name', 'client', 'ip']
        for table, cols in schema.items():
            colnames = [c.get('Field') for c in cols if c.get('Field')]
            lower = [c.lower() for c in colnames]
            cand_uname = None
            for c in colnames:
                if c.lower() in uname_cols:
                    cand_uname = c
                    break
            if not cand_uname:
                continue
            time_cols = [c for c in colnames if any(k in c.lower() for k in time_keywords)]
            if not time_cols:
                continue
            tcol = time_cols[0]
            # select a few informative columns if present
            pick_cols = [c for c in colnames if any(k in c.lower() for k in pick_cols_keywords)]
            cols_list = [cand_uname, tcol] + pick_cols
            cols_sql = ", ".join(f"`{c}`" for c in dict.fromkeys(cols_list))
            in_list = ", ".join([f"'{u}'" for u in usernames])
            sql = (
                f"SELECT {cols_sql} FROM `{table}` WHERE `{cand_uname}` IN ({in_list}) "
                f"AND `{tcol}` >= NOW() - INTERVAL {days} DAY ORDER BY `{tcol}` DESC LIMIT {limit}"
            )
            try:
                rows, columns = execute_sql_readonly(db_name, sql)
                if rows:
                    return rows, columns, sql
            except Exception:
                continue
        return [], [], 'fallback: подходящих таблиц/данных не найдено'
    except Exception as e:
        return [], [], f'fallback error: {e}'


def _extract_target_usernames(nl_pre: str, alias_map: dict, all_usernames: list) -> list:
    """From NL query, extract usernames explicitly mentioned or via surname mapping."""
    text = nl_pre or ''
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё._-]+", text)
    result = set()
    # explicit usernames
    lower_all = {u.lower(): u for u in all_usernames}
    for t in tokens:
        if t.lower() in lower_all:
            result.add(lower_all[t.lower()])
    # surnames
    for t in tokens:
        key = t.lower()
        if key in alias_map:
            for u in alias_map[key]:
                result.add(u)
    return sorted(result)


def _smb_fallback_files_activity(usernames: list, days: int = 7, limit: int = 100):
    """SMB-specific fallback using known working schema from smb blueprint.
    Returns (rows, columns, sql) or ([], [], reason)."""
    if not usernames:
        return [], [], 'no usernames'
    in_list = ", ".join([f"'{u}'" for u in usernames])
    sql = (
        "SELECT f.path, h.open_time, h.close_time, h.initial_size, h.final_size, u.username "
        "FROM smb_session_history h "
        "JOIN smb_files f ON h.file_id = f.id "
        "JOIN smb_users u ON h.user_id = u.id "
        f"WHERE u.username IN ({in_list}) AND h.open_time >= NOW() - INTERVAL {days} DAY "
        "ORDER BY h.open_time DESC "
        f"LIMIT {limit}"
    )
    try:
        rows, columns = execute_sql_readonly('smbstat', sql)
        return rows, columns, sql
    except Exception as e:
        return [], [], f'smb fallback error: {e}'

@bp.route('/query', methods=['GET', 'POST'])
@admin_required
def query():
    ensure_ai_tables()
    dbs = ['auto'] + list_databases()
    context = {
        'dbs': dbs,
        'selected_db': 'auto',
        'nl_query': '',
        'results': [],  # list of {db, sql, rows, columns}
        'summary_lines': [],
    }

    if request.method == 'POST':
        selected_db = request.form.get('db', 'auto')
        nl_query = request.form.get('q', '').strip()
        context.update({'selected_db': selected_db, 'nl_query': nl_query})
        if not nl_query:
            flash('Уточните запрос', 'warning')
            return render_template('ai/query.html', **context)
        try:
            # Build users context and enhance NL by replacing unique surnames to usernames
            usernames = sorted(collect_known_usernames())
            alias_map = build_alias_map()
            nl_pre = enhance_nl_with_aliases(nl_query, alias_map)
            context['nl_query'] = nl_pre

            # Determine target DBs
            target_dbs = [selected_db] if selected_db in list_databases() else _detect_candidate_dbs(nl_pre)

            results = []
            summary = []
            target_users = _extract_target_usernames(nl_pre, alias_map, usernames)
            for db_name in target_dbs:
                try:
                    schema = introspect_schema(db_name)
                    sql = _openai_generate_sql(nl_pre, db_name, schema, usernames, alias_map)
                    if not is_safe_sql(sql):
                        raise ValueError('Сгенерированный SQL не прошёл проверку безопасности')
                    rows, cols = execute_sql_readonly(db_name, sql)
                    # fallback if empty but we know the target usernames
                    fb_sql_info = None
                    if not rows and target_users:
                        if db_name == 'smbstat':
                            fb_rows, fb_cols, fb_sql = _smb_fallback_files_activity(target_users)
                            if not fb_rows:
                                fb_rows, fb_cols, fb_sql = _fallback_activity_query(db_name, target_users)
                        else:
                            fb_rows, fb_cols, fb_sql = _fallback_activity_query(db_name, target_users)
                        if fb_rows:
                            rows, cols = fb_rows, fb_cols
                            fb_sql_info = fb_sql
                    results.append({'db': db_name, 'sql': sql, 'rows': rows, 'columns': cols})
                    if fb_sql_info:
                        # append fallback SQL note for visibility
                        results[-1]['sql'] = sql + "\n-- fallback used: " + fb_sql_info
                    summary.append(_summarize_rows(db_name, rows, cols))
                    username = (session.get('user') or {}).get('username', 'admin')
                    audit_query(username, db_name, nl_query, sql, True, None, len(rows))
                except Exception as inner_e:
                    results.append({'db': db_name, 'sql': str(inner_e), 'rows': [], 'columns': []})
                    summary.append(f"{db_name}: ошибка — {inner_e}")
                    username = (session.get('user') or {}).get('username', 'admin')
                    audit_query(username, db_name, nl_query, None, False, str(inner_e), 0)

            context['results'] = results
            context['summary_lines'] = summary
        except Exception as e:
            username = (session.get('user') or {}).get('username', 'admin')
            # audit general failure (no DB)
            audit_query(username, selected_db if selected_db != 'auto' else 'auto', nl_query, None, False, str(e), 0)
            flash(f'Ошибка: {e}', 'error')
    return render_template('ai/query.html', **context)
