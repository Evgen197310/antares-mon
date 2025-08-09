# Единая система мониторинга сетевой инфраструктуры

Объединённое Flask веб-приложение для мониторинга VPN (IKEv2), RDP и SMB активности в сетевой инфраструктуре.

## 🚀 Возможности

### VPN Мониторинг (IKEv2)
- ✅ Просмотр активных VPN сессий
- ✅ История подключений пользователей
- ✅ Статистика использования VPN
- ✅ Интеграция с MikroTik роутерами

### RDP Мониторинг
- ✅ Активные RDP сессии в реальном времени
- ✅ История подключений всех пользователей
- ✅ Детальная статистика по пользователям
- ✅ Группировка сессий и фильтрация

### SMB Мониторинг
- ✅ Открытые файлы и активные сессии
- ✅ Мониторинг файловой активности пользователей
- ✅ Скачивание файлов через SSH
- ✅ Детальная история работы с файлами

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
│   │   └── filters.py           # Jinja2 фильтры
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
Убедитесь, что файл `/etc/infra/config.json` содержит настройки баз данных:

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
    }
  }
}
```

### 4. Структура баз данных

#### База данных: vpnstat
```sql
CREATE TABLE session_history (
    username VARCHAR(255),
    outer_ip VARCHAR(45),
    inner_ip VARCHAR(45), 
    time_start DATETIME,
    time_end DATETIME,
    duration INT
);
```

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
Используйте endpoint `/api/health` для мониторинга:
```bash
#!/bin/bash
response=$(curl -s http://localhost:8000/api/health)
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

### Настройка HTTPS с nginx (пример)
```nginx
server {
    listen 443 ssl;
    server_name monitoring.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    # Рекомендуемые заголовки
    add_header X-Frame-Options SAMEORIGIN always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer-when-downgrade;
    add_header X-XSS-Protection "1; mode=block";

    # Сжатие
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;

    # Проксирование к gunicorn
    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
    }

    # Health-check (опционально)
    location /health {
        proxy_pass http://127.0.0.1:5050/health;
        access_log off;
    }
}
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
**Последнее обновление**: 2025-08-08
