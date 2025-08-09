#!/usr/bin/env python3
import re
from ipaddress import ip_network, ip_address
import sys
import subprocess
import json
import os
import csv

CONFIG_PATH = '/etc/infra/config.json'

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def load_map(map_file):
    """
    Загружает карту MikroTik.
    Поддерживает два формата:
    1) ip|name
    2) identity,ip,mask,interface,flag (CSV)
    Возвращает dict: ip -> name
    """
    ip_to_name = {}
    with open(map_file, 'r') as f:
        first_line = f.readline()
        f.seek(0)
        if '|' in first_line:  # короткий формат
            for line in f:
                line = line.strip()
                if not line or '|' not in line:
                    continue
                ip, name = line.split('|', 1)
                ip_to_name[ip.strip()] = name.strip()
        else:  # CSV-формат
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 2:
                    continue
                identity, ip = row[0].strip(), row[1].strip()
                if not ip or ip.lower() == 'ip':
                    continue
                ip_to_name[ip] = identity
    return ip_to_name

def ssh_cmd(ip, cmd, ssh_user, ssh_key):
    ssh_command = [
        "ssh",
        "-i", ssh_key,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/root/.ssh/known_hosts",
        f"{ssh_user}@{ip}",
        cmd
    ]
    try:
        result = subprocess.run(
            ssh_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60
        )
        return result.stdout.decode('utf-8', 'ignore')
    except Exception:
        return ''

def parse_address_list(raw, list_name):
    result = set()
    for line in raw.splitlines():
        if list_name in line:
            m = re.search(r'{}\s+((?:\d{{1,3}}\.){{3}}\d{{1,3}}(?:/\d{{1,2}})?)'.format(re.escape(list_name)), line)
            if m:
                result.add(m.group(1))
    return result

def is_private(ip):
    try:
        return ip_address(ip).is_private
    except Exception:
        return False

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

    ip_to_name = load_map(map_file)

    intranet_subnets = {}
    myrouters_ips = {}
    for ip, name in ip_to_name.items():
        if is_private(ip):
            subnet = str(ip_network(f"{ip}/24", strict=False))
            intranet_subnets[subnet] = (ip, name)
        else:
            myrouters_ips[ip] = name

    for router_ip in router_access_ips:
        cur_intranet = parse_address_list(
            ssh_cmd(router_ip, f'/ip firewall address-list print where list="{intranet_list_name}"', ssh_user, ssh_key),
            intranet_list_name
        )
        cur_myrouters = parse_address_list(
            ssh_cmd(router_ip, f'/ip firewall address-list print where list="{myrouters_list_name}"', ssh_user, ssh_key),
            myrouters_list_name
        )

        for subnet, (base_ip, owner_name) in intranet_subnets.items():
            if subnet not in cur_intranet:
                cmd = f'/ip firewall address-list add list={intranet_list_name} address={subnet} comment="{base_ip} {owner_name}"'
                ssh_cmd(router_ip, cmd, ssh_user, ssh_key)

        for ip, owner_name in myrouters_ips.items():
            if ip == router_ip:
                continue
            if ip not in cur_myrouters:
                cmd = f'/ip firewall address-list add list={myrouters_list_name} address={ip} comment="{owner_name}"'
                ssh_cmd(router_ip, cmd, ssh_user, ssh_key)

if __name__ == '__main__':
    main()
