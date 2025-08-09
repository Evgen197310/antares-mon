#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from ipaddress import ip_network, ip_address
import sys
import subprocess
import json
import os
import csv
from typing import Dict, Set, Tuple, List

CONFIG_PATH = '/etc/infra/config.json'

def load_config() -> dict:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_map(map_file: str) -> Dict[str, str]:
    """
    Загружает карту MikroTik.
    Поддерживает:
    1) ip|name
    2) CSV: identity,ip,mask,interface,flag
    Возвращает dict: ip -> name (identity)
    """
    ip_to_name: Dict[str, str] = {}
    with open(map_file, 'r', encoding='utf-8') as f:
        first = f.readline()
        f.seek(0)
        if '|' in first:  # короткий формат
            for line in f:
                line = line.strip()
                if not line or '|' not in line:
                    continue
                ip, name = line.split('|', 1)
                ip_to_name[ip.strip()] = name.strip()
        else:  # CSV-формат
            reader = csv.reader(f)
            for row in reader:
                if not row or len(row) < 2:
                    continue
                identity = (row[0] or '').strip()
                ip = (row[1] or '').strip()
                if not ip or ip.lower() == 'ip':
                    continue
                ip_to_name[ip] = identity or ip
    return ip_to_name

def ssh_cmd(ip: str, cmd: str, ssh_user: str, ssh_key: str, timeout_sec: int = 20) -> Tuple[int, str, str]:
    """
    Выполняет команду по SSH на RouterOS.
    Возвращает (rc, stdout, stderr).
    Настройки — строго без интерактива.
    """
    ssh_command = [
        "ssh",
        "-i", ssh_key,
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/root/.ssh/known_hosts",
        "-o", "PreferredAuthentications=publickey",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "ConnectTimeout=8",
        "-o", "ConnectionAttempts=1",
        "-o", "ServerAliveInterval=5",
        "-o", "ServerAliveCountMax=2",
        f"{ssh_user}@{ip}",
        cmd
    ]
    try:
        result = subprocess.run(
            ssh_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_sec,
            check=False
        )
        stdout = result.stdout.decode('utf-8', 'ignore')
        stderr = result.stderr.decode('utf-8', 'ignore')
        return result.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout after {timeout_sec}s"
    except Exception as e:
        return 255, "", f"Exception: {e}"

ADDRESS_RE = re.compile(r'address=([0-9./]+)')
# Поддержка табличного вывода без detail: начало строки может содержать адрес в первой колонке
ADDRESS_COL_RE = re.compile(r'^\s*(?:\d+\s+)?([0-9]{1,3}(?:\.[0-9]{1,3}){3}(?:/\d{1,2})?)\b')

def parse_address_list_detail(raw: str) -> Set[str]:
    """Парсинг из вида '... address=1.2.3.0/24 ...'"""
    result: Set[str] = set()
    for line in raw.splitlines():
        m = ADDRESS_RE.search(line)
        if m:
            result.add(m.group(1))
    return result

def parse_address_list_table(raw: str) -> Set[str]:
    """Парсинг табличного 'print' без detail — адрес как первая колонка."""
    result: Set[str] = set()
    for line in raw.splitlines():
        m = ADDRESS_COL_RE.search(line)
        if m:
            result.add(m.group(1))
    return result

def get_address_list(router_ip: str, list_name: str, ssh_user: str, ssh_key: str) -> Tuple[Set[str], List[str]]:
    """
    Возвращает множество адресов в списке (сеть/адрес) и список диагностических сообщений.
    Пробует несколько вариантов для совместимости v6/v7.
    """
    diag: List[str] = []

    variants = [
        # v7 обычно ок
        f'/ip firewall address-list/print detail without-paging where list="{list_name}"',
        # v6/семь без "detail without-paging"
        f'/ip firewall address-list print where list="{list_name}"',
        # иногда кавычки мешают
        f'/ip firewall address-list print where list={list_name}',
        # detail без without-paging
        f'/ip firewall address-list print detail where list="{list_name}"',
    ]

    # Для каждого варианта пробуем два парсера
    for cmd in variants:
        rc, out, err = ssh_cmd(router_ip, cmd, ssh_user, ssh_key)
        if rc != 0:
            diag.append(f'cmd="{cmd}" rc={rc} err="{err.strip()}"')
            continue

        # 1) detail-парсер
        s_detail = parse_address_list_detail(out)
        if s_detail:
            diag.append(f'cmd="{cmd}" -> detail parse {len(s_detail)}')
            return s_detail, diag

        # 2) табличный парсер
        s_table = parse_address_list_table(out)
        if s_table:
            diag.append(f'cmd="{cmd}" -> table parse {len(s_table)}')
            return s_table, diag

        diag.append(f'cmd="{cmd}" -> no matches')

    # Финально: пусто
    return set(), diag

def is_private(ip: str) -> bool:
    try:
        return ip_address(ip).is_private
    except Exception:
        return False

def shell_escape_comment(s: str) -> str:
    return s.replace('"', r'\"')

def ensure_list_entries(router_ip: str,
                        list_name: str,
                        desired: Set[str],
                        current: Set[str],
                        comment_for: Dict[str, str],
                        ssh_user: str,
                        ssh_key: str) -> None:
    to_add = sorted(desired - current)
    if not to_add:
        print(f"[{router_ip}] {list_name}: всё актуально ({len(current)}).")
        return
    for addr in to_add:
        comment = shell_escape_comment(comment_for.get(addr, "auto"))
        cmd = f'/ip firewall address-list add list="{list_name}" address={addr} comment="{comment}"'
        rc, out, err = ssh_cmd(router_ip, cmd, ssh_user, ssh_key)
        if rc == 0:
            print(f"[{router_ip}] + {list_name}: {addr} ({comment})")
        else:
            print(f"[{router_ip}] ! add {list_name} {addr} failed rc={rc}: {err.strip()}")

def main():
    config = load_config()

    map_file = config["paths"]["mikrotik_map"]
    mikrotik_conf = config.get("mikrotik", {})
    router_access_ips = mikrotik_conf.get("router_access_ips", [])
    intranet_list_name = mikrotik_conf.get("intranet_list_name", "MY-INTRANET")
    myrouters_list_name = mikrotik_conf.get("myrouters_list_name", "MY-ROUTERS")

    ssh_params = config["remote_host"]["mikrotik"]
    ssh_user = ssh_params["ssh_user"]
    ssh_key = ssh_params["ssh_key"]

    if not os.path.isfile(ssh_key):
        print(f"[FATAL] SSH key not found: {ssh_key}", file=sys.stderr)
        sys.exit(2)

    ip_to_name = load_map(map_file)

    intranet_subnets: Dict[str, Tuple[str, str]] = {}
    myrouters_ips: Dict[str, str] = {}
    for ip, name in ip_to_name.items():
        if is_private(ip):
            subnet = str(ip_network(f"{ip}/24", strict=False))
            intranet_subnets.setdefault(subnet, (ip, name))
        else:
            myrouters_ips[ip] = name

    desired_intranet: Set[str] = set(intranet_subnets.keys())
    desired_myrouters: Set[str] = set(myrouters_ips.keys())

    intranet_comments = {subnet: f"{base_ip} {owner}" for subnet, (base_ip, owner) in intranet_subnets.items()}
    myrouters_comments = {ip: owner for ip, owner in myrouters_ips.items()}

    if not router_access_ips:
        print("[WARN] Список router_access_ips пуст — нечего синхронизировать.")
        return

    for router_ip in router_access_ips:
        print(f"\n== Обработка роутера {router_ip} ==")

        # Тянем текущие списки с фоллбэком и диагностикой
        cur_intranet, diag1 = get_address_list(router_ip, intranet_list_name, ssh_user, ssh_key)
        if not cur_intranet:
            print(f"[{router_ip}] ! Не удалось получить {intranet_list_name}: пустой результат.")
            for d in diag1:
                print(f"[{router_ip}]   {d}")
            # продолжаем, но добавлять будет всё «с нуля»
        else:
            # Если ранее было rc=1, теперь увидим через diag, какой вариант сработал
            pass

        cur_myrouters, diag2 = get_address_list(router_ip, myrouters_list_name, ssh_user, ssh_key)
        if not cur_myrouters:
            print(f"[{router_ip}] ! Не удалось получить {myrouters_list_name}: пустой результат.")
            for d in diag2:
                print(f"[{router_ip}]   {d}")

        # INTRANET
        ensure_list_entries(
            router_ip,
            intranet_list_name,
            desired_intranet,
            cur_intranet,
            intranet_comments,
            ssh_user,
            ssh_key
        )

        # MY-ROUTERS (не добавляем самого себя)
        filtered_desired_myrouters = {ip for ip in desired_myrouters if ip != router_ip}
        ensure_list_entries(
            router_ip,
            myrouters_list_name,
            filtered_desired_myrouters,
            cur_myrouters,
            myrouters_comments,
            ssh_user,
            ssh_key
        )

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Прервано пользователем.", file=sys.stderr)
        sys.exit(130)
