#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import pymysql
import os
import sys
import re
from collections import defaultdict

CONFIG_PATH = "/etc/infra/config.json"

def load_config() -> Dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def get_smbstat_connection(cfg):
    db = cfg["mysql"]["smbstat"]
    return pymysql.connect(
        host=db["host"],
        user=db["user"],
        password=db["password"],
        database=db["database"],
        charset=db.get("charset", "utf8mb4"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )

def get_rdp_connection(cfg):
    db = cfg["mysql"]["rdpstat"]
    return pymysql.connect(
        host=db["host"],
        user=db["user"],
        password=db["password"],
        database=db["database"],
        charset=db.get("charset", "utf8mb4"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )

def setup_logging(cfg):
    log_dir = cfg["paths"]["smbmon_log_dir"]
    log_file = cfg["paths"]["smbmon_log_file"]
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_file,
        filemode='a',
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

def log_debug(msg):
    print("[DEBUG]", msg)
    logging.info("[DEBUG] " + msg)

def log_exception(exc: Exception) -> None:
    print(f"[ERROR] ❌ {exc}")
    logging.exception(f"❌ Исключение: {exc}")

def normalize_user(u: str) -> str:
    if not u:
        return ""
    u = u.replace('/', '\\')
    base = u.split('\\')[-1]
    return base.lower()

def merge_intervals(intervals):
    if not intervals:
        return []
    def end_key(e):
        return e[1] if e[1] is not None else datetime.max
    intervals.sort(key=lambda x: (x[0], end_key(x)))
    merged = [intervals[0]]
    for st, en in intervals[1:]:
        mst, men = merged[-1]
        cur_end = men if men is not None else datetime.max
        new_end = en if en is not None else datetime.max
        if st <= cur_end:
            if new_end > cur_end:
                merged[-1] = (mst, en)
        else:
            merged.append((st, en))
    return merged

def load_rdp_intervals(cfg, candidate_users: List[str]):
    result = defaultdict(list)
    if not candidate_users:
        return result
    uniq = sorted(set(candidate_users))
    fmt = ",".join(["%s"] * len(uniq))
    try:
        conn = get_rdp_connection(cfg)
    except Exception as e:
        log_debug(f"RDP connect failed: {e}")
        return result
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT username, login_time
                FROM rdp_active_sessions
                WHERE LOWER(username) IN ({fmt})
                  AND login_time IS NOT NULL
            """, tuple(uniq))
            for r in cur.fetchall():
                nu = normalize_user(r["username"])
                result[nu].append((r["login_time"], None))
            cur.execute(f"""
                SELECT username, login_time, logout_time
                FROM rdp_session_history
                WHERE LOWER(username) IN ({fmt})
                  AND login_time IS NOT NULL
                  AND logout_time IS NOT NULL
            """, tuple(uniq))
            for r in cur.fetchall():
                st = r["login_time"]
                en = r["logout_time"]
                if en and en < st:
                    st, en = en, st
                nu = normalize_user(r["username"])
                result[nu].append((st, en))
        for u in list(result.keys()):
            result[u] = merge_intervals(result[u])
    except Exception as e:
        log_debug(f"Ошибка загрузки RDP интервалов: {e}")
        return defaultdict(list)
    finally:
        conn.close()
    return result

def ts_in_intervals(ts: datetime, intervals) -> bool:
    if not ts or not intervals:
        return False
    for st, en in intervals:
        right = en if en is not None else datetime.max
        if st <= ts < right:
            return True
    return False

def get_open_files(cfg) -> List[Dict]:
    ssh_cfg = cfg["remote_host"]["smb_server"]
    ssh_host = ssh_cfg["ssh_host"]
    ssh_user = ssh_cfg["ssh_user"]
    ssh_key = ssh_cfg["ssh_key"]

    monitored_ext = cfg["monitored_extensions"]
    ext_re = '|'.join([e.lstrip('.') for e in monitored_ext])

    ps_command = (
        "powershell -NoLogo -NoProfile -Command "
        "\"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
        "$files = Get-SmbOpenFile | "
        f"Where-Object {{ $_.Path.ToLower() -match '\\.({ext_re})$' -and -not ($_.Path -like '*\\~$*') }}; "
        "$files | ForEach-Object { "
        "   $size = $null; "
        "   try { $size = (Get-Item $_.Path).Length } catch {} "
        "   [PSCustomObject]@{ "
        "       ClientUserName = $_.ClientUserName; "
        "       Path = $_.Path; "
        "       ClientComputerName = $_.ClientComputerName; "
        "       SessionId = $_.SessionId; "
        "       Length = $size "
        "   } "
        "} | ConvertTo-Json -Compress\""
    )

    ssh_cmd = [
        "ssh",
        "-q",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/root/.ssh/known_hosts",
        "-i", ssh_key,
        f"{ssh_user}@{ssh_host}",
        ps_command
    ]

    log_debug(f"SSH CMD: {' '.join(ssh_cmd)}")
    result = subprocess.run(
        ssh_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60
    )
    try:
        output = result.stdout.decode('utf-8').strip()
    except UnicodeDecodeError:
        output = result.stdout.decode('cp1251', errors='replace').strip()

    if result.returncode != 0:
        try:
            err = result.stderr.decode('utf-8')
        except UnicodeDecodeError:
            err = result.stderr.decode('cp1251', errors='replace')
        log_debug(f"SSH ERROR: {err}")
        raise RuntimeError(f"Ошибка SSH:\n{err}")

    log_debug("STDOUT:\n" + output)
    if output.startswith("["):
        return json.loads(output)
    elif output:
        return [json.loads(output)]
    return []

def now() -> datetime:
    return datetime.now().replace(microsecond=0)

def norm_path(path: str) -> str:
    return path.replace('\\', '/').lower()

def get_or_create_id(cur, table, value, col='path', ext_insert=None):
    log_debug(f"get_or_create_id: table={table}, value={value}, col={col}")
    sql = f"SELECT id FROM {table} WHERE {col}=%s"
    cur.execute(sql, (value,))
    row = cur.fetchone()
    if row:
        log_debug(f"Found existing id={row['id']} for {value} in {table}")
        return row['id']
    if table == 'smb_files':
        normval = norm_path(value)
        cur.execute("INSERT INTO smb_files (path, norm_path) VALUES (%s, %s)", (value, normval))
    elif table == 'smb_users':
        cur.execute("INSERT INTO smb_users (username) VALUES (%s)", (value,))
    elif table == 'smb_clients':
        cur.execute("INSERT INTO smb_clients (host) VALUES (%s)", (value,))
    else:
        if ext_insert:
            cur.execute(ext_insert, (value,))
        else:
            raise Exception(f"Неизвестная таблица: {table}")
    new_id = cur.lastrowid
    log_debug(f"Inserted new id={new_id} for {value} in {table}")
    return new_id

def get_file_size_ssh(cfg, path):
    ssh_cfg = cfg["remote_host"]["smb_server"]
    ssh_host = ssh_cfg["ssh_host"]
    ssh_user = ssh_cfg["ssh_user"]
    ssh_key = ssh_cfg["ssh_key"]
    ps_cmd = f"(Get-Item -LiteralPath '{path}').Length"
    ssh_cmd = [
        "ssh", "-q",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/root/.ssh/known_hosts",
        "-i", ssh_key,
        f"{ssh_user}@{ssh_host}",
        f"powershell -NoLogo -NoProfile -Command \"{ps_cmd}\""
    ]
    result = subprocess.run(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    output = result.stdout.decode('utf-8', errors='replace').strip()
    if result.returncode == 0 and output.isdigit():
        return int(output)
    else:
        print(f"[ERROR] Не удалось получить размер для {path}: {output}")
        return None

def process_sessions(cfg, open_files):
    now_ts = now()
    added = {}
    closed = {}

    conn = get_smbstat_connection(cfg)
    cur = conn.cursor(pymysql.cursors.DictCursor)

    cur.execute("SELECT * FROM active_smb_sessions")
    db_sessions = {(r["file_id"], r["user_id"], r["client_id"], r["session_id"]): r for r in cur.fetchall()}
    seen_keys = set()

    smb_usernames_current = set()
    for entry in open_files:
        smb_usernames_current.add(normalize_user(entry["ClientUserName"]))
    if db_sessions:
        cur.execute("SELECT id, username FROM smb_users WHERE id IN %s" %
                    "(" + ",".join({str(r["user_id"]) for r in db_sessions.values()}) + ")")
        for rr in cur.fetchall():
            smb_usernames_current.add(normalize_user(rr["username"]))

    rdp_map = load_rdp_intervals(cfg, list(smb_usernames_current))

    for entry in open_files:
        raw_path = entry["Path"]
        user = entry["ClientUserName"]
        host = entry["ClientComputerName"]
        session_id = str(entry["SessionId"])

        file_id = get_or_create_id(cur, 'smb_files', raw_path, 'path')
        user_id = get_or_create_id(cur, 'smb_users', user, 'username')
        client_id = get_or_create_id(cur, 'smb_clients', host, 'host')
        key = (file_id, user_id, client_id, session_id)
        seen_keys.add(key)

        file_size = entry.get("Length")
        if file_size is None:
            file_size = get_file_size_ssh(cfg, raw_path)

        if key in db_sessions:
            if db_sessions[key]['initial_size'] is None and file_size is not None:
                cur.execute(
                    "UPDATE active_smb_sessions SET initial_size=%s WHERE id=%s",
                    (file_size, db_sessions[key]["id"])
                )
            cur.execute(
                "UPDATE active_smb_sessions SET last_seen=%s WHERE id=%s",
                (now_ts, db_sessions[key]["id"])
            )
        else:
            norm_user = normalize_user(user)
            intervals = rdp_map.get(norm_user, [])
            open_in_rdp = 1 if ts_in_intervals(now_ts, intervals) else 0

            cur.execute(
                "INSERT INTO active_smb_sessions "
                "(file_id, user_id, client_id, session_id, open_time, initial_size, last_seen, open_in_rdp) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (file_id, user_id, client_id, session_id, now_ts, file_size, now_ts, open_in_rdp)
            )
            added[user] = added.get(user, 0) + 1

    for key, dbs in db_sessions.items():
        if key not in seen_keys:
            duration = int((now_ts - dbs["open_time"]).total_seconds())
            final_size = dbs["initial_size"]
            cur.execute("SELECT path FROM smb_files WHERE id=%s", (dbs["file_id"],))
            row = cur.fetchone()
            file_path = row['path'] if row else None
            if file_path:
                size_now = get_file_size_ssh(cfg, file_path)
                if size_now is not None:
                    final_size = size_now
            open_in_rdp_val = dbs.get("open_in_rdp", 0)
            cur.execute(
                "INSERT INTO smb_session_history "
                "(file_id, user_id, client_id, session_id, open_time, close_time, duration_sec, "
                " initial_size, final_size, open_in_rdp) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    dbs["file_id"],
                    dbs["user_id"],
                    dbs["client_id"],
                    dbs["session_id"],
                    dbs["open_time"],
                    now_ts,
                    duration,
                    dbs["initial_size"],
                    final_size,
                    open_in_rdp_val
                )
            )
            cur.execute("DELETE FROM active_smb_sessions WHERE id=%s", (dbs["id"],))
            closed[dbs['user_id']] = closed.get(dbs['user_id'], 0) + 1

    cur.close()
    conn.close()

    total_new = sum(added.values())
    total_closed = sum(closed.values())
    if total_new > 0:
        print(f"\n📊 Добавлено новых сессий: {total_new}")
        for usr, cnt in sorted(added.items()):
            print(f"    - {usr}: {cnt}")
    if total_closed > 0:
        print(f"\n📉 Закрыто сессий (перенесено в историю): {total_closed}")
        for uid, cnt in sorted(closed.items()):
            print(f"    - user_id={uid}: {cnt}")

def main():
    cfg = load_config()
    setup_logging(cfg)
    logging.info("Запуск smbmon (мониторинг и запись в БД)")
    try:
        exclude_regex = cfg.get("exclude_path_regex")
        pattern = re.compile(exclude_regex) if exclude_regex else None
        open_files = get_open_files(cfg)
        log_debug(f"Получено {len(open_files)} открытых файлов.")
        if pattern:
            open_files = [f for f in open_files if not pattern.search(f["Path"])]
            log_debug(f"После фильтрации по exclude_path_regex осталось: {len(open_files)} файлов.")
        process_sessions(cfg, open_files)
    except Exception as exc:
        log_exception(exc)
        sys.exit(1)

if __name__ == "__main__":
    main()
