#!/usr/bin/env python3
import os
import subprocess
import json
import pymysql
import csv
from datetime import datetime


CONFIG_PATH = "/etc/rdpmon/config.json"

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def fetch_file(config):
    scp_cmd = [
        "scp", "-i", config["ssh"]["key_path"],
        f'{config["ssh"]["user"]}@{config["ssh"]["host"]}:{config["ssh"]["remote_json"]}',
        config["local_json"]
    ]
    result = subprocess.run(scp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print("❌ Ошибка SCP:", result.stderr.decode())
        return False
    return True



def export_active_sessions_to_json(config, output_file):
    conn = pymysql.connect(
        host=config["mysql"]["host"],
        user=config["mysql"]["user"],
        password=config["mysql"]["password"],
        database=config["mysql"]["database"],
        charset='utf8mb4'
    )
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute("SELECT * FROM rdp_active_sessions")
    rows = cur.fetchall()

    def convert(obj):
        if isinstance(obj, datetime):
            return obj.isoformat(sep=' ')
        return obj

    def dict_convert(row):
        return {k: convert(v) for k, v in row.items()}

    rows_clean = [dict_convert(r) for r in rows]

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(rows_clean, f, ensure_ascii=False, indent=2)

    cur.close()
    conn.close()
    print(f"📝 Экспортировано в {output_file}")

import csv
import pymysql

def export_active_sessions_to_csv(config, output_file):
    conn = pymysql.connect(
        host=config["mysql"]["host"],
        user=config["mysql"]["user"],
        password=config["mysql"]["password"],
        database=config["mysql"]["database"],
        charset='utf8mb4'
    )
    cur = conn.cursor()
    cur.execute("SELECT * FROM rdp_active_sessions")
    rows = cur.fetchall()
    headers = [i[0] for i in cur.description]

    with open(output_file, "w", newline='', encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    cur.close()
    conn.close()
    print(f"📝 Экспортировано в {output_file}")


def update_active_sessions(sessions, config):
    conn = pymysql.connect(
        host=config["mysql"]["host"],
        user=config["mysql"]["user"],
        password=config["mysql"]["password"],
        database=config["mysql"]["database"],
        charset='utf8mb4'
    )
    cur = conn.cursor(pymysql.cursors.DictCursor)
    now = datetime.now()

    # Загружаем текущие активные сессии
    cur.execute("SELECT * FROM rdp_active_sessions")
    old_sessions = {(r["username"], str(r["session_id"])): r for r in cur.fetchall()} # type: ignore

    seen_keys = set()
    inserted = 0
    closed = 0

    state_map = {
        0: "Активная",
        1: "Подключён",
        2: "Запрос подключения",
        3: "Теневой режим",
        4: "Отключён",
        5: "Простой",
        6: "Недоступна",
        7: "Инициализация",
        8: "Сброшена",
        9: "Ожидание"
    }

    for s in sessions:
        session_state = s.get("SessionState")
        state_label = state_map.get(session_state, f"Unknown({session_state})")

        if session_state not in (0, 1):
            username = s.get("UserName", "")
            session_id = s.get("SessionId", "")
            print(f"[SKIP] {username:<15} SID {session_id:<4} [{state_label}] — пропущено (не активна)")
            continue

        username = s.get("UserName", "")
        domain = s.get("DomainName", "")
        session_id = str(s.get("SessionId"))
        state = str(session_state)
        key = (username, session_id)
        seen_keys.add(key)

        old = old_sessions.get(key)
        login_time = old["login_time"] if old else now # type: ignore
        duration_seconds = int((now - login_time).total_seconds())

        cur.execute("""
            INSERT INTO rdp_active_sessions
                (username, domain, collection_name, remote_host, login_time,
                 state, session_id, notes, duration_seconds, last_update)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
                remote_host=VALUES(remote_host),
                state=VALUES(state),
                notes=VALUES(notes),
                duration_seconds=VALUES(duration_seconds),
                last_update=CURRENT_TIMESTAMP
        """, (
            username,
            domain,
            s.get("CollectionName", ""),
            s.get("HostServer", ""),
            login_time.strftime("%Y-%m-%d %H:%M:%S"),
            state,
            session_id,
            s.get("ApplicationType", ""),
            duration_seconds
        ))

        inserted += 1
        print(f"[OK  ] {username:<15} SID {session_id:<4} [{state_label}] — активна, обновлена, длительность {duration_seconds} сек.")

    # Сохраняем в историю те сессии, которых больше нет
    for key, old in old_sessions.items():
        if key not in seen_keys:
            cur.execute("""
                INSERT INTO rdp_session_history
                    (username, domain, collection_name, remote_host,
                     login_time, logout_time, duration_seconds, session_id, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                old["username"],
                old["domain"],
                old["collection_name"],
                old["remote_host"],
                old["login_time"],
                now,
                int((now - old["login_time"]).total_seconds()),
                old["session_id"],
                old["notes"]
            ))
            cur.execute("DELETE FROM rdp_active_sessions WHERE id=%s", (old["id"],))
            closed += 1
            print(f"[END ] {old['username']:<15} SID {old['session_id']:<4} — завершена, перенесена в историю.")

    conn.commit()
    cur.close()
    conn.close()

    print(f"\n✅ Обработано: {len(sessions)} сессий")
    print(f"➕ Активных записей обновлено: {inserted}")
    print(f"🗑️  Завершено и перенесено в историю: {closed}")

import time

def fetch_sessions(config, retries=6, delay=5):
    """
    Читает локальный JSON-файл сессий, при ошибке повторяет попытку через delay секунд.
    Количество попыток задаётся параметром retries (по умолчанию 6 попыток = 30 секунд ожидания).
    """
    path = config["local_json"]
    for attempt in range(1, retries+1):
        if not os.path.exists(path):
            print(f"❌ [{attempt}] Локальный JSON не найден: {path}")
        else:
            try:
                with open(path, encoding="utf-8-sig") as f:
                    data = json.load(f)
                    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
                        print(f"❌ [{attempt}] Некорректный формат JSON: ожидался список словарей, получено {type(data)}")
                        raise ValueError("Некорректный формат данных")
                    print(f"🟢 [{attempt}] Успешно считан файл {path}, сессий: {len(data)}")
                    return data
            except Exception as e:
                print(f"❌ [{attempt}] Ошибка чтения JSON: {e}")
        if attempt < retries:
            print(f"⏳ Повторная попытка через {delay} сек...")
            time.sleep(delay)
        else:
            print("❌ Превышено максимальное число попыток чтения файла.")
    return []


def main():
    config = load_config()
    print(f"[{datetime.now()}] ⏳ Получаем файл сессий по SCP...")
    if not fetch_file(config):
        return
    sessions = fetch_sessions(config)
    print(f"[{datetime.now()}] 🟢 Сессий всего в файле: {len(sessions)}")
    update_active_sessions(sessions, config)
    export_active_sessions_to_json(config, config["export_json"])
    export_active_sessions_to_csv(config, config["export_csv"])
    print(f"[{datetime.now()}] ✅ rdp_active_sessions обновлена")

if __name__ == "__main__":
    main()
