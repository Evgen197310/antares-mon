#!/usr/bin/env python3
import subprocess
import json
import re
import pymysql
import csv
from datetime import datetime

CONFIG_PATH = "/etc/rdpmon/config.json"

def parse_win_date(datestr):
    match = re.search(r"\/Date\((\d+)\)\/", datestr)
    if match:
        ts = int(match.group(1)) / 1000
        return datetime.fromtimestamp(ts)
    return None

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def fetch_events(ssh_host, ssh_user, ssh_key_path):
    cmd = [
        "ssh", "-i", ssh_key_path,
        f"{ssh_user}@{ssh_host}",
        "powershell -File C:\\Scripts\\extract_rdp_events.ps1"
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = result.stdout.decode("utf-8", errors="ignore")
    if result.returncode != 0:
        print("❌ Ошибка получения логов по SSH:")
        print(result.stderr.decode("utf-8", errors="ignore"))
        exit(1)
    try:
        return json.loads(out)
    except Exception as e:
        print("❌ Ошибка парсинга JSON:", e)
        print("Фрагмент вывода:\n", out[:1000])
        exit(1)

def extract_sessions(events):
    sessions = []
    for e in events:
        if e.get("EventType") != "login":
            continue
        rawuser = e.get("Username", "")
        if "\\" in rawuser:
            domain, username = rawuser.split("\\", 1)
        else:
            domain, username = "", rawuser
        username = username.lower()
        server = e.get("Server", "")
        server_ip = e.get("ServerIP", "")
        time_login = parse_win_date(e.get("TimeCreated", ""))
        if not username or not server or not time_login:
            continue
        sessions.append({
            "username": username,
            "domain": domain,
            "collection_name": server,
            "remote_host": server_ip,
            "login_time": time_login,
            "connection_type": "broker"
        })
    return sessions

def save_to_csv(sessions, csv_path):
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["username", "domain", "collection_name", "remote_host", "login_time", "connection_type"])
        for s in sessions:
            writer.writerow([
                s["username"], s["domain"], s["collection_name"], s["remote_host"],
                s["login_time"].strftime("%Y-%m-%d %H:%M:%S"),
                s["connection_type"]
            ])

def save_to_db(sessions, config):
    conn = pymysql.connect(
        host=config["mysql"]["host"],
        user=config["mysql"]["user"],
        password=config["mysql"]["password"],
        database=config["mysql"]["database"],
        charset='utf8mb4'
    )
    cur = conn.cursor()
    for s in sessions:
        cur.execute("""
            INSERT INTO rdp_session_history
            (username, domain, collection_name, remote_host, login_time, connection_type)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                domain=VALUES(domain),
                remote_host=VALUES(remote_host),
                connection_type=VALUES(connection_type)
        """, (
            s["username"], s["domain"], s["collection_name"], s["remote_host"],
            s["login_time"].strftime("%Y-%m-%d %H:%M:%S"),
            s["connection_type"]
        ))
    conn.commit()
    cur.close()
    conn.close()

def main():
    config = load_config()
    print("📡 Получаем историю через SSH ...")
    events = fetch_events(
        ssh_host=config["ssh"]["host"],
        ssh_user=config["ssh"]["user"],
        ssh_key_path=config["ssh"]["key_path"]
    )
    sessions = extract_sessions(events)
    print(f"✅ Сессий для импорта: {len(sessions)}")
    for s in sessions[:20]:
        print(f"{s['username']:20} {s['domain']:10} {s['collection_name']:30} {s['remote_host']:15} {s['login_time']} {s['connection_type']}")
    csv_path = config.get("export_csv", "/var/log/rdp/rdp_active.csv")
    save_to_csv(sessions, csv_path)
    save_to_db(sessions, config)
    print("✅ Импорт завершён (MySQL + CSV)")

if __name__ == "__main__":
    main()
