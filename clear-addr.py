#!/usr/bin/env python3
import sys
import subprocess
import json

# Путь до основного конфига инфраструктуры
CONFIG_PATH = '/etc/infra/config.json'

def load_config():
    """
    Загружает конфигурацию из CONFIG_PATH и возвращает как dict.
    """
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def ssh_cmd(ip, cmd, ssh_user, ssh_key):
    """
    Выполняет SSH-команду на удалённом MikroTik.
    Возвращает stdout в виде строки (str).
    ip        — адрес для подключения
    cmd       — команда RouterOS
    ssh_user  — пользователь SSH
    ssh_key   — путь к приватному ключу
    """
    ssh_command = [
        "ssh",
        "-i", ssh_key,                               # Ключ для подключения
        "-o", "StrictHostKeyChecking=no",            # Не спрашивать подтверждение
        "-o", "UserKnownHostsFile=/root/.ssh/known_hosts",  # Хранить known_hosts в указанном файле
        f"{ssh_user}@{ip}",                          # Логин и IP
        cmd                                          # Команда для RouterOS
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
    """
    Проверяет, есть ли указанная подсеть/адрес в списке (list_name) на роутере.
    Если есть — удаляет.
    router_ip   — IP для подключения
    list_name   — имя списка (MY-INTRANET или MY-ROUTERS)
    target      — удаляемая подсеть/адрес
    ssh_user    — SSH-пользователь
    ssh_key     — SSH-ключ
    """
    # Проверяем, есть ли этот адрес/подсеть в списке
    check_cmd = f'/ip firewall address-list print where list={list_name} address={target}'
    check_out = ssh_cmd(router_ip, check_cmd, ssh_user, ssh_key)

    if target in check_out:
        # Если найдено — удаляем
        del_cmd = f'/ip firewall address-list remove [find list={list_name} address={target}]'
        ssh_cmd(router_ip, del_cmd, ssh_user, ssh_key)
        print(f"  {list_name}: удалено {target}")
    else:
        # Если не найдено — сообщаем
        print(f"  {list_name}: {target} не найдено")

def main():
    """
    Основная функция:
    - Загружает конфиг
    - Получает список роутеров для доступа
    - Проходит по каждому роутеру и удаляет указанный адрес/подсеть
      из списков MY-INTRANET и MY-ROUTERS
    """
    if len(sys.argv) != 2:
        print(f"Использование: {sys.argv[0]} <подсеть/адрес>")
        sys.exit(1)

    # Подсеть или адрес, который нужно удалить
    target = sys.argv[1]

    # Загружаем конфигурацию
    config = load_config()

    # Настройки Mikrotik из конфига
    mikrotik_conf = config.get("mikrotik", {})
    router_access_ips = mikrotik_conf.get("router_access_ips", [])
    intranet_list_name = mikrotik_conf.get("intranet_list_name", "MY-INTRANET")
    myrouters_list_name = mikrotik_conf.get("myrouters_list_name", "MY-ROUTERS")

    # SSH-параметры подключения к MikroTik
    ssh_params = config["remote_hosts"]["mikrotik"]
    ssh_user = ssh_params["ssh_user"]
    ssh_key = ssh_params["ssh_key"]

    # Проходим по каждому роутеру и удаляем адрес из двух списков
    for router_ip in router_access_ips:
        print(f"\n--- {router_ip} ---")
        remove_from_list(router_ip, intranet_list_name, target, ssh_user, ssh_key)
        remove_from_list(router_ip, myrouters_list_name, target, ssh_user, ssh_key)

if __name__ == '__main__':
    main()
