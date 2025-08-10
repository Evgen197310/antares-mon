#!/usr/bin/env python3
import sys
import subprocess
import json

CONFIG_PATH = '/etc/infra/config.json'


def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)


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
            timeout=30
        )
        return result.stdout.decode('utf-8', 'ignore').strip()
    except Exception as e:
        return str(e)


def remove_from_list(router_ip, list_name, target, ssh_user, ssh_key):
    check_cmd = f'/ip firewall address-list print where list={list_name} address={target}'
    check_out = ssh_cmd(router_ip, check_cmd, ssh_user, ssh_key)

    if target in check_out:
        del_cmd = f'/ip firewall address-list remove [find list={list_name} address={target}]'
        ssh_cmd(router_ip, del_cmd, ssh_user, ssh_key)
        print(f"  {list_name}: удалено {target}")
    else:
        print(f"  {list_name}: {target} не найдено")


def main():
    if len(sys.argv) != 2:
        print(f"Использование: {sys.argv[0]} <подсеть/адрес>")
        sys.exit(1)

    target = sys.argv[1]
    config = load_config()

    mikrotik_conf = config.get("mikrotik", {})
    router_access_ips = mikrotik_conf.get("router_access_ips", [])
    intranet_list_name = mikrotik_conf.get("intranet_list_name", "MY-INTRANET")
    myrouters_list_name = mikrotik_conf.get("myrouters_list_name", "MY-ROUTERS")

    # поддержка разных блоков конфига
    ssh_params = (
        config.get("remote_hosts", {}).get("mikrotik")
        or config.get("remote_host", {}).get("mikrotik")
        or {"ssh_user": "", "ssh_key": ""}
    )
    ssh_user = ssh_params.get("ssh_user")
    ssh_key = ssh_params.get("ssh_key")

    for router_ip in router_access_ips:
        print(f"\n--- {router_ip} ---")
        remove_from_list(router_ip, intranet_list_name, target, ssh_user, ssh_key)
        remove_from_list(router_ip, myrouters_list_name, target, ssh_user, ssh_key)


if __name__ == '__main__':
    main()
