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

### Режим продакшн (с Gunicorn)
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 run:app
```

### Systemd сервис
Создайте файл `/etc/systemd/system/monitoring-web.service`:

```ini
[Unit]
Description=Network Monitoring Web Application
After=network.target mysql.service

[Service]
Type=exec
User=monitoring
Group=monitoring
WorkingDirectory=/opt/monitoring-web
Environment=FLASK_ENV=production
ExecStart=/usr/bin/python3 run.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Активация:
```bash
sudo systemctl daemon-reload
sudo systemctl enable monitoring-web
sudo systemctl start monitoring-web
```

## 🌐 Использование

### Веб-интерфейс
- **Главная страница**: `http://localhost:8000/`
- **VPN мониторинг**: `http://localhost:8000/vpn/`
- **RDP мониторинг**: `http://localhost:8000/rdp/`
- **SMB мониторинг**: `http://localhost:8000/smb/`

### REST API
- **API документация**: `http://localhost:8000/api/`
- **Состояние системы**: `http://localhost:8000/api/health`
- **Общий статус**: `http://localhost:8000/api/status`

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
curl http://localhost:8000/api/vpn/sessions

# Получить историю RDP сессий пользователя
curl "http://localhost:8000/api/rdp/history?username=john&limit=50"

# Проверить состояние системы
curl http://localhost:8000/api/health

# Получить общую статистику
curl http://localhost:8000/api/status
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
Логи записываются в stdout и могут быть перенаправлены:
```bash
python run.py > /var/log/monitoring-web.log 2>&1
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

### Настройка HTTPS с nginx
```nginx
server {
    listen 443 ssl;
    server_name monitoring.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
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
