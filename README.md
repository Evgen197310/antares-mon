## 📦 Развертывание инфраструктурных модулей MikroTik

Скопируйте скрипты проекта в системный каталог и назначьте права:

```bash
install -Dm0755 scripts/mikrotik-discover.sh /usr/local/bin/mikrotik-discover.sh
install -Dm0755 scripts/auto-rsyslog-rules-generate.sh /usr/local/bin/auto-rsyslog-rules-generate.sh
install -Dm0755 scripts/sync-lists.py /usr/local/bin/sync-lists.py
install -Dm0755 scripts/clear-addr.py /usr/local/bin/clear-addr.py
```

Затем выполните подготовку (однократно):

```bash
mkdir -p /var/lib/mikrotik /var/log/mikrotik
/usr/local/bin/mikrotik-discover.sh
/usr/local/bin/auto-rsyslog-rules-generate.sh
systemctl restart rsyslog
/usr/local/bin/sync-lists.py
```

И настройте cron (пример):

```
0 3 * * * /usr/local/bin/mikrotik-discover.sh && /usr/local/bin/auto-rsyslog-rules-generate.sh && systemctl restart rsyslog && /usr/local/bin/sync-lists.py >> /var/log/mikrotik_discover.log 2>&1
```
### Частые проблемы и решения

- __[DB: доступ/пермишены]__
  - Симптомы: `Access denied for user`, `Unknown database`, таймауты.
  - Проверьте `config.json` (`mysql.host`, `mysql.user`, `mysql.password`, имена БД `vpnstat/rdpstat/smbstat`).
  - Убедитесь в правах: `SHOW GRANTS FOR 'user'@'host'` содержит SELECT (и INSERT/UPDATE, если требуется).
  - Проверьте сетевой доступ с хоста приложения до MySQL (`telnet <host> 3306` или `mysql -h ...`).

- __[DB: кодировка/часовой пояс]__
  - Для корректного отображения кириллицы и дат используйте `utf8mb4` и TZ сервера: `SET time_zone = '+03:00';`.
  - В шаблонах применяются фильтры `datetime_format`, `time_ago`; несоответствие TZ даст неверные длительности.

- __[DB: пул соединений]__
  - Симптомы: подвисание при пиковой нагрузке.
  - Уменьшите частоту автообновления страниц/дашборда, проверьте лимиты MySQL `max_connections`.

- __[SSH: аутентификация]__
  - Симптомы: `Permission denied (publickey)`, `no matching host key type`.
  - Проверьте путь к ключу и его права `chmod 600 /path/to/key`.
  - Сверьте тип ключа/алгоритмы на сервере (ed25519/rsa) и known_hosts.
  - Убедитесь, что хост и порт совпадают с `remote_host.smb_server`/`ssh_port` в `config.json`.

- __[SSH: сеть/фаервол]__
  - Проверьте доступ по порту 22/кастомному: `nc -vz smb.example.com 22`.
  - Если используется jump-host/bastion — настройте ProxyCommand/ProxyJump или соответствующие поля в конфиге.

- __[VPN: CSV активных сессий]__
  - Симптомы: пустой список VPN-сессий на дашборде при наличии активных подключений.
  - Проверьте путь к CSV в `/etc/infra/config.json` (ключ, используемый модулем VPN) и права чтения для пользователя сервиса.
  - Убедитесь, что генератор CSV выполняется и обновляет файл (cron/systemd timer), время модификации файла актуально (`stat <file>`).
  - Проверьте разделители и заголовок CSV: соответствие ожидаемому формату (имена колонок, кодировка UTF-8).
  - CSV активных VPN-сессий должен регулярно обновляться внешним генератором (cron/systemd timer); время модификации файла должно быть актуальным.
  - Формат CSV активных VPN-сессий (без/с заголовком): `username,outer_ip,inner_ip,time_start[,router]`.
  Пример строки: `ivanov,203.0.113.10,192.168.91.23,2025-08-10 09:15:00,MT-Core`.
  - Путь к карте MikroTik также может задаваться через конфиг приложения `MIKROTIK_MAP_FILE` (по умолчанию `/opt/ike2web/data/full_map.csv`).

- __[Systemd: не стартует сервис]__
  - Смотрите `journalctl -u monitoring-web -n 200 -f` — часто проблемы с PYTHONPATH/конфигом.
  - Проверьте переменные окружения в unit-файле: `FLASK_PORT=5050`, `FLASK_HOST=0.0.0.0`, `PYTHONPATH=/opt/monitoring-web`.

- __[Nginx: 502/504]__
  - Увеличьте `proxy_read_timeout`/`proxy_connect_timeout`.
  - Убедитесь, что приложение слушает 127.0.0.1:5050 и живо (`curl -f http://127.0.0.1:5050/health`).

# Единая система мониторинга сетевой инфраструктуры

Объединённое Flask веб-приложение для мониторинга VPN (IKEv2), RDP и SMB активности в сетевой инфраструктуре.

## 🚀 Возможности

### VPN Мониторинг (IKEv2)
- ✅ Просмотр активных VPN сессий
- ✅ История подключений пользователей
- ✅ Статистика использования VPN
- ✅ Интеграция с MikroTik роутерами
 - ✅ Отображение активных пользователей на дашборде (кликабельно)
 - ✅ Кликабельные карточки на странице VPN: «Активные сессии», «За сегодня», «Устройств MikroTik», «Средняя длительность»
 - ✅ Человекочитаемые длительности (дни/часы/минуты/секунды)
 - ✅ Определение «Маршрутизатора» по внутреннему IP через карту MikroTik (по попаданию IP в подсеть интерфейса)

### RDP Мониторинг
- ✅ Активные RDP сессии в реальном времени
- ✅ История подключений всех пользователей
- ✅ Детальная статистика по пользователям
- ✅ Группировка сессий и фильтрация
 - ✅ Список активных пользователей на дашборде (кликабельно, с подсказкой коллекции)

### SMB Мониторинг
- ✅ Открытые файлы и активные сессии
- ✅ Мониторинг файловой активности пользователей
- ✅ Скачивание файлов через SSH
- ✅ Детальная история работы с файлами
 - ✅ Список открытых файлов на дашборде (кликабельно, тултип с полным путём)

### REST API
- ✅ Полноценный REST API для всех модулей
- ✅ JSON endpoints для интеграции
- ✅ Проверка состояния системы
- ✅ Статистика и метрики

## 🏗️ Архитектура

```
monitoring-web/
├── app/
│   ├── __init__.py              # Фабрика Flask приложения
│   ├── config.py                # Конфигурация
│   ├── blueprints/              # Модули приложения
│   │   ├── main.py              # Главная страница
│   │   ├── vpn.py               # VPN мониторинг
│   │   ├── rdp.py               # RDP мониторинг
│   │   ├── smb.py               # SMB мониторинг
│   │   └── api.py               # REST API
│   ├── models/
│   │   └── database.py          # Менеджер баз данных
│   ├── utils/
│   │   └── filters.py           # Jinja2 фильтры: pretty_time, rusdatetime, human_filesize, basename, dt_to_str,
│   │                            # а также datetime_format, time_ago, duration_format (добавлен вывод дней)
│   ├── templates/               # HTML шаблоны
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── vpn/
│   │   ├── rdp/
│   │   └── smb/
│   └── static/                  # Статические файлы
│       ├── css/
│       ├── js/
│       └── images/
├── requirements.txt             # Python зависимости
├── run.py                      # Точка входа
├── scripts/                    # Инфраструктурные модули MikroTik
│   ├── mikrotik-discover.sh
│   ├── auto-rsyslog-rules-generate.sh
│   ├── sync-lists.py
│   └── clear-addr.py
└── README.md                   # Документация
```

## 🌍 Доступ извне

- __Прямой доступ без Nginx__: откройте порт 5050 на сервере/фаерволе и зайдите по адресу:
  - `http://<PUBLIC_IP>:5050/` или `http://<DOMAIN>:5050/`
  - Примеры: `http://203.0.113.10:5050/`, `http://monitoring.example.com:5050/`

- __firewalld (RHEL/CentOS/Rocky)__:
```bash
sudo firewall-cmd --add-port=5050/tcp --permanent
sudo firewall-cmd --reload
```

- __ufw (Ubuntu/Debian)__:
```bash
sudo ufw allow 5050/tcp
sudo ufw reload
```

- __NAT/роутер__: пробросьте внешний порт 5050 на IP сервера или используйте Nginx на 443 с проксированием на 127.0.0.1:5050 (см. раздел Nginx). Тогда вход снаружи будет по `https://<DOMAIN>/` без указания порта.

- __SELinux (если включен)__:
```bash
sudo setsebool -P httpd_can_network_connect 1   # для Nginx-прокси
```

После открытия порта/настройки Nginx доступен Веб‑UI:
```
Главная: http://<HOST>:5050/
VPN:     http://<HOST>:5050/vpn/
RDP:     http://<HOST>:5050/rdp/
SMB:     http://<HOST>:5050/smb/
API:     http://<HOST>:5050/api/
```

### Troubleshooting systemd/gunicorn

- __Проверить логи__: `journalctl -u monitoring-web -n 200 -f`
- __Порт занят__: освободить 5050, либо сменить `FLASK_PORT` в `/etc/default/monitoring-web` и `systemctl restart monitoring-web`.
- __Изменили unit/env и не видите эффекта__: `systemctl daemon-reload` после правок unit, затем `systemctl restart monitoring-web`.
- __Таймауты на длинных запросах__: увеличьте `--timeout` (например, 180) в `ExecStart` и/или `proxy_read_timeout` в nginx.
- __Нагрузка/производительность__: настройте число воркеров `--workers` (ориентир: CPU*2) и `--threads` (I/O-bound). Пример: `--workers 4 --threads 2`.
- __Грейсфул перезапуск__: добавьте в unit `ExecReload=/bin/kill -HUP $MAINPID` и используйте `systemctl reload monitoring-web`.
- __Пути/переменные окружения__: задайте через `/etc/default/monitoring-web` (см. раздел Systemd). Убедитесь, что `CONFIG_PATH` указывает на валидный JSON.
- __SELinux/AppArmor/Firewall__: проверьте разрешения на порт и доступ к файлам (`setenforce 0` для теста, затем корректные политики). Проверьте `firewalld`/`iptables`.
- __Проверка работоспособности__: `curl -sS http://127.0.0.1:5050/health` должен вернуть статус 200.

### Дополнительно: валидация источников VPN-данных
- CSV активных VPN-сессий: проверьте актуальность файла (`stat`), формат дат `YYYY-MM-DD HH:MM:SS` или `YYYY-MM-DDTHH:MM:SS[.fff]`.
- Карта MikroTik: убедитесь, что в CSV есть колонки `identity`, `ip`/`address` и маска (`/mask` или отдельным столбцом). Для строк без заголовка порядок: `identity, ip, mask, iface, flag`.
- Если «Маршрутизатор» не отображается, проверьте, попадает ли `inner_ip` в одну из подсетей из карты.

## 📋 Требования

### Системные требования
- Python 3.6+
- MySQL 5.7+ / MariaDB 10.2+
- SSH доступ к серверам (для SMB модуля)

### Python зависимости
```
Flask==2.3.3
PyMySQL==1.1.0
paramiko==3.3.1
cryptography==41.0.4
```

## 🛠️ Установка

### 1. Клонирование и подготовка
```bash
cd /opt
git clone <repository> monitoring-web
cd monitoring-web
```

### 2. Установка зависимостей
```bash
pip install -r requirements.txt
```

### 3. Конфигурация
Убедитесь, что файл `/etc/infra/config.json` содержит настройки баз данных. Дополнительно проверьте пути к источникам VPN-данных (CSV и карта MikroTik):

```json
{
  "mysql": {
    "vpnstat": {
      "host": "localhost",
      "user": "vpn_user",
      "password": "password",
      "database": "vpnstat",
      "charset": "utf8mb4"
    },
    "rdpstat": {
      "host": "localhost", 
      "user": "rdp_user",
      "password": "password",
      "database": "rdpstat",
      "charset": "utf8mb4"
    },
    "smbstat": {
      "host": "localhost",
      "user": "smb_user", 
      "password": "password",
      "database": "smbstat",
      "charset": "utf8mb4"
    }
  },
  "ssh": {
    "smb_server": {
      "host": "smb.example.com",
      "user": "admin",
      "key_file": "/path/to/ssh/key"
    },
    "remote_host": {
      "mikrotik": {
        "ssh_user": "mtadmin",
        "ssh_key": "/root/.ssh/id_ed25519"
      }
    },
    "remote_hosts": {                       
      "mikrotik": {                        
        "ssh_user": "mtadmin",           
        "ssh_key": "/root/.ssh/id_ed25519"
      }                                      
    }                                        
  }
}
```

Примечание: разные утилиты читают SSH-параметры из `mikrotik.*`, `remote_host.mikrotik` или `remote_hosts.mikrotik` (например, `clear-addr.py`). Рекомендуется задать все блоки одинаково для совместимости.

### 4. Структура баз данных

#### База данных: vpnstat
```sql
CREATE TABLE session_history (
    username VARCHAR(255),
    outer_ip VARCHAR(45),
    inner_ip VARCHAR(45), 
    time_start DATETIME,
    time_end DATETIME,
    -- duration (INT) опционально: приложение рассчитывает длительность через
    -- TIMESTAMPDIFF(SECOND, time_start, COALESCE(time_end, NOW())) AS duration_seconds
);
```

Использование полей в приложении:
- Для списков/истории длительность вычисляется на лету (не используется сохранённое `duration`).
- Поле «Маршрутизатор» не берётся из БД; определяется по попаданию `inner_ip` в подсети из «карты MikroTik».

#### База данных: rdpstat
```sql
CREATE TABLE rdp_active_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255),
    session_id VARCHAR(255),
    domain VARCHAR(255),
    collection_name VARCHAR(255),
    remote_host VARCHAR(255),
    login_time DATETIME,
    connection_type VARCHAR(50),
    state INT,
    duration_seconds INT,
    notes TEXT
);

CREATE TABLE rdp_session_history (
    username VARCHAR(255),
    domain VARCHAR(255),
    collection_name VARCHAR(255),
    remote_host VARCHAR(255),
    login_time DATETIME,
    connection_type VARCHAR(50)
);
```

#### База данных: smbstat
```sql
CREATE TABLE smb_users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(255) UNIQUE
);

CREATE TABLE smb_files (
    id INT AUTO_INCREMENT PRIMARY KEY,
    path TEXT,
    norm_path TEXT
);

CREATE TABLE smb_clients (
    id INT AUTO_INCREMENT PRIMARY KEY,
    host VARCHAR(255)
);

CREATE TABLE active_smb_sessions (
    user_id INT,
    file_id INT,
    client_id INT,
    session_id VARCHAR(255),
    open_time DATETIME,
    last_seen DATETIME,
    initial_size BIGINT,
    FOREIGN KEY (user_id) REFERENCES smb_users(id),
    FOREIGN KEY (file_id) REFERENCES smb_files(id),
    FOREIGN KEY (client_id) REFERENCES smb_clients(id)
);

CREATE TABLE smb_session_history (
    user_id INT,
    file_id INT,
    open_time DATETIME,
    close_time DATETIME,
    initial_size BIGINT,
    final_size BIGINT,
    FOREIGN KEY (user_id) REFERENCES smb_users(id),
    FOREIGN KEY (file_id) REFERENCES smb_files(id)
);
```

## 🛰️ Модули сканирования MikroTik и синхронизации списков (обязательная часть системы)

Для корректной работы VPN‑дашборда и логирования необходим регулярный сбор и обновление карты адресов MikroTik, а также синхронизация списков на самих роутерах.

- **`/usr/local/bin/mikrotik-discover.sh`**
  - Подключается по SSH к каждому адресу из `mikrotik.router_access_ips`.
  - Считывает `identity` и все активные IPv4 адреса интерфейсов.
  - Формирует:
    - "короткую" карту `ip|identity` → `paths.mikrotik_map_short` (для rsyslog)
    - "полную" карту CSV `identity,ip,mask,interface,flag` → `paths.mikrotik_map`

- **`/usr/local/bin/auto-rsyslog-rules-generate.sh`**
  - На основе `paths.mikrotik_map_short` генерирует файл правил rsyslog `paths.mikrotik_rsyslog_rules`,
    чтобы разносить логи MikroTik по файлам согласно `identity` в каталоге `paths.mikrotik_log`.
  - После генерации необходимо перезапустить rsyslog.

- **`/usr/local/bin/sync-lists.py`**
  - Читает "полную" карту из `paths.mikrotik_map`.
  - Формирует целевые наборы:
    - `MY-INTRANET` — приватные подсети по `/24` (на основе внутренних IP, вычисляется `x.y.z.0/24`).
    - `MY-ROUTERS` — публичные IP самих маршрутизаторов.
  - Для каждого роутера из `mikrotik.router_access_ips` подключается по SSH и дозакидывает недостающие записи в соответствующие `address-list`.
  - Имена списков настраиваются через `mikrotik.intranet_list_name` и `mikrotik.myrouters_list_name`.

- **`/usr/local/bin/clear-addr.py`**
  - Утилита для удаления конкретного адреса/подсети из списков `MY-INTRANET` и `MY-ROUTERS` на всех роутерах.
  - Использование: `clear-addr.py <addr_or_subnet>`.

### Планировщик (cron)

Рекомендуемый cron для пользователя `root` (пример):

```
0 3 * * * /usr/local/bin/mikrotik-discover.sh && /usr/local/bin/auto-rsyslog-rules-generate.sh && systemctl restart rsyslog && /usr/local/bin/sync-lists.py >> /var/log/mikrotik_discover.log 2>&1
```

Дополнительно (из текущего окружения):

```
*/1 * * * * /usr/bin/python3 /usr/local/bin/rdpmon_broker.py >> /var/log/rdpmon_broker.log 2>&1
# SMB монитор периодический
* 0 * * 6 /usr/bin/python3 /usr/local/bin/smbmon.py >> /var/log/smbmon_daemon.log 2>&1
* 8-23 * * 6 /usr/bin/python3 /usr/local/bin/smbmon.py >> /var/log/smbmon_daemon.log 2>&1
* * * * 0-5,7 /usr/bin/python3 /usr/local/bin/smbmon.py >> /var/log/smbmon_daemon.log 2>&1
```

После первого запуска убедитесь, что:
- `paths.mikrotik_map` и `paths.mikrotik_map_short` созданы и не пустые.
- Файл правил rsyslog `paths.mikrotik_rsyslog_rules` существует, и `systemctl restart rsyslog` завершился успешно.
- В каталоге `paths.mikrotik_log` появляются файлы логов по именам устройств.

### Как это используется приложением
- Веб‑приложение использует карту MikroTik для сопоставления `inner_ip` VPN‑сессии с именем маршрутизатора (по попаданию IP в подсеть интерфейса из карты).
- При отсутствии актуальной карты столбец «Маршрутизатор» может быть пуст — проверьте cron и доступ по SSH к устройствам.

## 🚀 Запуск

### Режим разработки
```bash
python run.py
```

### Режим продакшн (Gunicorn)
Рекомендуемый способ — запуск через Gunicorn и systemd. Точка входа — `wsgi.py`.

```bash
pip install gunicorn
# Локальный старт без systemd (для проверки)
gunicorn --workers 3 --threads 2 --timeout 120 --bind 0.0.0.0:5050 wsgi:app
```

### Systemd сервис (рекомендовано)
1) Файл окружения `/etc/default/monitoring-web`:
```bash
FLASK_PORT=5050
FLASK_HOST=0.0.0.0
FLASK_DEBUG=False
FLASK_TEMPLATES_AUTO_RELOAD=1
```

2) Unit-файл `/etc/systemd/system/monitoring-web.service`:
```ini
[Unit]
Description=Monitoring Web Application (Flask via Gunicorn)
After=network.target

[Service]
User=root
Group=root
WorkingDirectory=/opt/monitoring-web
EnvironmentFile=-/etc/default/monitoring-web
ExecStart=/usr/bin/python3 -m gunicorn --workers 3 --threads 2 --timeout 120 --bind 0.0.0.0:${FLASK_PORT} wsgi:app
Restart=always
RestartSec=2
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

3) Запуск и автозагрузка:
```bash
sudo systemctl daemon-reload
sudo systemctl enable monitoring-web
sudo systemctl restart monitoring-web
```

4) Проверка:
```bash
systemctl status --no-pager -l monitoring-web
journalctl -u monitoring-web -n 200 -f
```

#### Graceful reload (без простоя)
В unit-файл добавьте строку (у нас уже добавлено):
```
ExecReload=/bin/kill -HUP $MAINPID
```
После правок выполните:
```bash
sudo systemctl daemon-reload
sudo systemctl reload monitoring-web   # перечитает конфиг без остановки воркеров
```

## 🌐 Использование

### Веб-интерфейс
- **Главная страница**: `http://localhost:5050/`
- **VPN мониторинг**: `http://localhost:5050/vpn/`
- **RDP мониторинг**: `http://localhost:5050/rdp/`
- **SMB мониторинг**: `http://localhost:5050/smb/`

### REST API
- **API документация**: `http://localhost:5050/api/`
- **Состояние системы**: `http://localhost:5050/api/health`
- **Общий статус**: `http://localhost:5050/api/status`

#### VPN API
- `GET /api/vpn/sessions` - Активные VPN сессии
- `GET /api/vpn/history?limit=100&offset=0&username=user` - История сессий
- `GET /api/vpn/stats` - Статистика VPN
 
#### VPN страницы (новые маршруты)
- `GET /vpn/active-sessions` — список активных VPN-сессий (из CSV), с колонкой «Маршрутизатор».
- `GET /vpn/today-sessions` — VPN-сессии за сегодня (из `vpnstat.session_history`), длительность формируется человекочитаемо.
- `GET /vpn/devices` — устройства MikroTik/адреса интерфейсов из карты.
- `GET /vpn/user-stats?days=7|30|90|365` — статистика пользователей.

#### RDP API  
- `GET /api/rdp/sessions` - Активные RDP сессии
- `GET /api/rdp/history?limit=100&offset=0&username=user` - История сессий
- `GET /api/rdp/user/<username>` - Статистика пользователя

#### SMB API
- `GET /api/smb/sessions` - Активные SMB сессии
- `GET /api/smb/files?limit=100&offset=0` - Открытые файлы
- `GET /api/smb/users?limit=100&offset=0` - Пользователи SMB
- `GET /api/smb/stats` - Статистика SMB

### Примеры API запросов

```bash
# Получить активные VPN сессии
curl http://localhost:5050/api/vpn/sessions

# Получить историю RDP сессий пользователя
curl "http://localhost:5050/api/rdp/history?username=john&limit=50"

# Проверить состояние системы
curl http://localhost:5050/api/health

# Получить общую статистику
curl http://localhost:5050/api/status
```

## 🔧 Конфигурация

### Переменные окружения
```bash
export FLASK_ENV=production
export FLASK_DEBUG=0
export CONFIG_PATH=/etc/infra/config.json
```

### Настройки Flask
В `app/config.py` можно изменить:
- Порт приложения
- Настройки логирования
- Пути к конфигурационным файлам
- Параметры подключения к базам данных

## 📊 Мониторинг и логи

### Логи приложения
Через systemd/journalctl:
```bash
journalctl -u monitoring-web -n 200 -f
```

### Мониторинг состояния
UI health: `GET /health` возвращает JSON со следующими ключами:
- `status` (ok|degraded)
- `databases` (vpnstat/rdpstat/smbstat: ok|error)
- `server_time` (ISO8601)
- `uptime_seconds` (int)
- `last_update` (ISO8601)

API health: используйте endpoint `/api/health` для интеграций:
```bash
#!/bin/bash
response=$(curl -s http://localhost:5050/api/health)
status=$(echo $response | jq -r '.status')
if [ "$status" != "healthy" ]; then
    echo "ALERT: Monitoring system is $status"
    # Отправить уведомление
fi
```

## 🔒 Безопасность

### Рекомендации
1. **Ограничьте доступ** к веб-интерфейсу через firewall
2. **Используйте HTTPS** в продакшн среде
3. **Ограничьте права** MySQL пользователей
4. **Защитите SSH ключи** для SMB модуля
5. **Регулярно обновляйте** зависимости

### Настройка HTTPS с nginx (https://health.antares.ru/)
```nginx
# HTTP -> HTTPS redirect
server {
    listen 80;
    listen [::]:80;
    server_name health.antares.ru;
    return 301 https://$host$request_uri;
}

# HTTPS upstream to Flask app on 127.0.0.1:5050
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name health.antares.ru;

    # Сертификаты Let's Encrypt
    ssl_certificate /etc/letsencrypt/live/health.antares.ru/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/health.antares.ru/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/health.antares.ru/chain.pem;

    # Безопасные заголовки
    add_header X-Frame-Options SAMEORIGIN always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer-when-downgrade;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Сжатие
    gzip on;
    gzip_comp_level 5;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript image/svg+xml;

    # Клиентские лимиты
    client_max_body_size 20m;

    # Основной прокси к приложению
    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 180s;
        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_redirect off;
    }

    # Health-check (легковесный)
    location /health {
        proxy_pass http://127.0.0.1:5050/health;
        access_log off;
    }

    # API (опционально, отдельные правила)
    location /api/ {
        proxy_pass http://127.0.0.1:5050/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 180s;
    }
}

# Проверка и перезапуск nginx:
# sudo nginx -t && sudo systemctl reload nginx
```

## 🐛 Устранение неполадок

### Проблемы с базой данных
```bash
# Проверить подключение к MySQL
mysql -h localhost -u vpn_user -p vpnstat -e "SELECT 1"

# Проверить права пользователя
mysql -u root -p -e "SHOW GRANTS FOR 'vpn_user'@'localhost'"
```

### Проблемы с SSH (SMB модуль)
```bash
# Проверить SSH подключение
ssh -i /path/to/key user@smb.example.com "echo 'Connection OK'"

# Проверить права на ключ
chmod 600 /path/to/ssh/key
```

### Отладка приложения
```bash
# Запуск в режиме отладки
export FLASK_DEBUG=1
python run.py
```

## 📝 Разработка

### Структура проекта
- **Blueprints**: Каждый модуль (VPN, RDP, SMB, API) - отдельный blueprint
- **Templates**: Используется наследование от `base.html`
- **Database**: Контекстные менеджеры для безопасной работы с БД
- **Filters**: Jinja2 фильтры для форматирования данных

### Добавление нового модуля
1. Создайте blueprint в `app/blueprints/`
2. Добавьте шаблоны в `app/templates/`
3. Зарегистрируйте blueprint в `app/__init__.py`
4. Добавьте API endpoints в `app/blueprints/api.py`

### Тестирование
```bash
# Запуск тестов структуры
python test_app.py

# Проверка синтаксиса
python -m py_compile app/*.py app/blueprints/*.py
```

## 📞 Поддержка

При возникновении проблем:
1. Проверьте логи приложения
2. Убедитесь в корректности конфигурации
3. Проверьте подключения к базам данных
4. Используйте `/api/health` для диагностики

## 📄 Лицензия

Внутренний проект для мониторинга сетевой инфраструктуры.

---

**Версия**: 2.0.0  
**Последнее обновление**: 2025-08-09
