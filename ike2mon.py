#!/usr/bin/env python3
import re
import time
import os
import datetime
import pymysql
import subprocess
import json
import sys

CONFIG_PATH = '/etc/infra/config.json'

def load_config(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

try:
    CONFIG = load_config(CONFIG_PATH)
except Exception as e:
    print(f"[FATAL] Не удалось загрузить конфиг: {e}")
    sys.exit(1)

# --- Пути и параметры ---
LOG_FILE         = CONFIG['paths']['mikrotik_log']
STATE_FILE       = CONFIG['paths']['ikev2_state_file']

MYSQL_SETTINGS   = CONFIG['mysql']['vpnstat']

SSH_HOST         = CONFIG['remote_host']['mikrotik']['ssh_host']
SSH_USER         = CONFIG['remote_host']['mikrotik']['ssh_user']
SSH_KEY          = CONFIG['remote_host']['mikrotik']['ssh_key']
SSH_PASSWORD     = None  # Только если понадобится; по умолчанию ключ

SYNC_INTERVAL    = 300  # можно вынести в конфиг, если понадобится

acquired_re = re.compile(
    r'.*acquired (?P<inner_ip>\d+\.\d+\.\d+\.\d+) address for (?P<outer_ip>\d+\.\d+\.\d+\.\d+), (?:CN=(?P<cn>[^,]+)|(?P<altname>[^,]+))'
)
releasing_re = re.compile(
    r'.*releasing address (?P<inner_ip>\d+\.\d+\.\d+\.\d+)'
)

sessions = {}

def parse_iso8601(s):
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError("Unknown timestamp format: " + s)

def current_timestamp():
    return datetime.datetime.now().isoformat()

def save_to_mysql(username, outer_ip, inner_ip, ts_start, ts_end, duration):
    try:
        db = pymysql.connect(**MYSQL_SETTINGS)
        with db:
            with db.cursor() as c:
                c.execute(
                    "INSERT INTO session_history (username, outer_ip, inner_ip, time_start, time_end, duration) VALUES (%s, %s, %s, %s, %s, %s)",
                    (username, outer_ip, inner_ip, ts_start, ts_end, duration)
                )
            db.commit()
    except Exception as e:
        print("Ошибка при записи в MySQL:", e)

def save_state():
    with open(STATE_FILE, 'w') as f:
        for username, outer_ip, inner_ip, ts in sessions.values():
            f.write(f'{username},{outer_ip},{inner_ip},{ts}\n')

def add_session(username, outer_ip, inner_ip):
    sessions[inner_ip] = (username, outer_ip, inner_ip, current_timestamp())
    save_state()

def remove_session(inner_ip):
    inner_ip = inner_ip.strip()
    if inner_ip not in sessions:
        print(f"[WARN] {inner_ip} not in sessions")
        return

    username, outer_ip, inner_ip, ts_start = sessions[inner_ip]
    ts_end   = current_timestamp()
    duration = int((parse_iso8601(ts_end) - parse_iso8601(ts_start)).total_seconds())
    save_to_mysql(username, outer_ip, inner_ip, ts_start, ts_end, duration)

    del sessions[inner_ip]
    try:
        save_state()
    except Exception as e:
        print("[ERROR] Не могу сохранить CSV:", e)

def process_line(line):
    m = acquired_re.search(line)
    if m:
        print("  > Найдено подключение", m.groupdict(), flush=True)
        cn = m.group('cn')
        altname = m.group('altname')
        username = (cn if cn else altname).strip()
        outer_ip = m.group('outer_ip')
        inner_ip = m.group('inner_ip')
        add_session(username, outer_ip, inner_ip)
        return

    m = releasing_re.search(line)
    if m:
        print("  > Найдено отключение", m.groupdict(), flush=True)
        inner_ip = m.group('inner_ip').strip()
        remove_session(inner_ip)
        return

def initial_scan():
    if os.path.isfile(STATE_FILE):
        os.remove(STATE_FILE)
    sessions.clear()
    with open(LOG_FILE, 'r') as f:
        for line in f:
            m = acquired_re.search(line)
            if m:
                cn = m.group('cn')
                altname = m.group('altname')
                username = (cn if cn else altname).strip()
                outer_ip = m.group('outer_ip')
                inner_ip = m.group('inner_ip')
                sessions[inner_ip] = (username, outer_ip, inner_ip, current_timestamp())
            m = releasing_re.search(line)
            if m:
                inner_ip = m.group('inner_ip').strip()
                sessions.pop(inner_ip, None)
    save_state()

def ssh_get_active_peers():
    peers = set()
    ssh_command = [
        "ssh",
        "-q",
        "-i", SSH_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/root/.ssh/known_hosts",
        f"{SSH_USER}@{SSH_HOST}",
        '/ip ipsec active-peers print detail'
    ]
    try:
        result = subprocess.run(
            ssh_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60
        )
        out = result.stdout.decode('utf-8', 'ignore')
    except Exception as e:
        print(f"[SSH ERROR] {e}")
        out = ''
    cur_user = cur_outer = cur_inner = None
    for ln in out.splitlines():
        if 'l2tp-in-server' in ln:
            cur_user = cur_outer = cur_inner = None
            continue
        m = re.search(r'id="(?:CN=)?([^,"]+)', ln)
        if not m:
            m = re.search(r'^\s*\d+\s+[RN]+\s+([^\s;]+)', ln)
        if m:
            cur_user = m.group(1)
        m = re.search(r'remote-address=([\d\.]+)', ln)
        if m:
            cur_outer = m.group(1)
        m = re.search(r'dynamic-address=([\d\.]+)', ln)
        if m:
            cur_inner = m.group(1)
        if cur_user and cur_inner:
            peers.add((cur_user, cur_outer, cur_inner))
            cur_user = cur_outer = cur_inner = None
    return peers

def sync_with_router():
    print("[SYNC] Начинаем сверку с MikroTik...", flush=True)
    active_peers = ssh_get_active_peers()
    ssh_set = set(active_peers)
    if active_peers is None:
        print("[SYNC] Ошибка SSH, сверка пропущена!")
        return

    local_set = set((v[0], v[1], v[2]) for v in sessions.values())

    # Удалить фантомные (которых нет на MikroTik)
    for k, v in list(sessions.items()):
        triple = (v[0], v[1], v[2])
        if triple not in ssh_set:
            print(f"[SYNC] Фантом: {triple}, удаляем.")
            remove_session(k)

    # Добавить новые, если на MikroTik есть, а у нас нет
    for triple in ssh_set:
        if triple not in local_set:
            print(f"[SYNC] Новая сессия: {triple}, добавляем.")
            add_session(*triple)

    save_state()
    print("[SYNC] Сверка завершена.", flush=True)

def follow(file):
    file.seek(0, 2)
    t_last_sync = time.time()
    while True:
        line = file.readline()
        if not line:
            if time.time() - t_last_sync > SYNC_INTERVAL:
                sync_with_router()
                t_last_sync = time.time()
            time.sleep(0.5)
            continue
        process_line(line)

def main():
    print("Сервис стартовал", flush=True)
    initial_scan()
    sync_with_router()
    while True:
        try:
            with open(LOG_FILE, 'r') as f:
                follow(f)
        except Exception as e:
            print(f"Ошибка: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
