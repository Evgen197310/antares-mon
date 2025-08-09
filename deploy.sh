#!/bin/bash

# Скрипт развертывания единого приложения мониторинга
# Версия: 2.0.0

set -e  # Остановка при ошибках

echo "🚀 Начинаем развертывание единого приложения мониторинга..."

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функция логирования
log() {
    echo -e "${BLUE}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Проверка окружения
check_environment() {
    log "Проверка окружения..."
    
    # Проверка Python
    if ! command -v python3 &> /dev/null; then
        error "Python3 не найден!"
        exit 1
    fi
    
    python_version=$(python3 --version | cut -d' ' -f2)
    log "Python версия: $python_version"
    
    # Проверка MySQL
    if ! command -v mysql &> /dev/null; then
        warning "MySQL клиент не найден. Убедитесь, что MySQL сервер доступен."
    fi
    
    # Проверка конфигурационного файла
    if [[ ! -f "/etc/infra/config.json" ]]; then
        error "Конфигурационный файл /etc/infra/config.json не найден!"
        exit 1
    fi
    
    success "Окружение проверено"
}

# Установка зависимостей
install_dependencies() {
    log "Установка Python зависимостей..."
    
    if [[ ! -f "requirements.txt" ]]; then
        error "Файл requirements.txt не найден!"
        exit 1
    fi
    
    pip3 install -r requirements.txt
    success "Зависимости установлены"
}

# Создание директорий
create_directories() {
    log "Создание необходимых директорий..."
    
    sudo mkdir -p /var/log/monitoring-web
    sudo chown $(whoami):$(whoami) /var/log/monitoring-web
    
    success "Директории созданы"
}

# Тестирование структуры приложения
test_structure() {
    log "Тестирование структуры приложения..."
    
    # Проверка основных файлов
    required_files=(
        "app/__init__.py"
        "app/config.py"
        "app/blueprints/main.py"
        "app/blueprints/vpn.py"
        "app/blueprints/rdp.py"
        "app/blueprints/smb.py"
        "app/blueprints/api.py"
        "app/models/database.py"
        "app/utils/filters.py"
        "app/templates/base.html"
        "run.py"
    )
    
    for file in "${required_files[@]}"; do
        if [[ ! -f "$file" ]]; then
            error "Отсутствует файл: $file"
            exit 1
        fi
    done
    
    # Проверка синтаксиса Python
    log "Проверка синтаксиса Python файлов..."
    find app/ -name "*.py" -exec python3 -m py_compile {} \;
    python3 -m py_compile run.py
    
    success "Структура приложения корректна"
}

# Тестирование подключений к базам данных
test_databases() {
    log "Тестирование подключений к базам данных..."
    
    python3 -c "
import sys
sys.path.append('.')
from app.models.database import db_manager
from app.config import Config

config = Config()
print('Тестирование подключений к БД...')

for db_type in ['vpn', 'rdp', 'smb']:
    try:
        with db_manager.get_connection(db_type) as conn:
            with conn.cursor() as cursor:
                cursor.execute('SELECT 1')
                result = cursor.fetchone()
                print(f'✅ {db_type.upper()} база данных: OK')
    except Exception as e:
        print(f'❌ {db_type.upper()} база данных: {e}')
        sys.exit(1)

print('Все базы данных доступны!')
"
    
    if [[ $? -eq 0 ]]; then
        success "Подключения к базам данных работают"
    else
        error "Проблемы с подключением к базам данных"
        exit 1
    fi
}

# Запуск приложения в тестовом режиме
test_application() {
    log "Запуск приложения в тестовом режиме..."
    
    # Запуск на короткое время для проверки
    timeout 10s python3 run.py &
    app_pid=$!
    
    sleep 5
    
    # Проверка, что приложение запустилось
    if kill -0 $app_pid 2>/dev/null; then
        log "Приложение успешно запустилось (PID: $app_pid)"
        
        # Тестирование основных endpoints
        log "Тестирование основных endpoints..."
        
        # Проверка главной страницы
        if curl -s -f http://localhost:5050/ > /dev/null; then
            success "Главная страница доступна"
        else
            warning "Главная страница недоступна"
        fi
        
        # Проверка API health
        if curl -s -f http://localhost:5050/api/health > /dev/null; then
            success "API health endpoint доступен"
        else
            warning "API health endpoint недоступен"
        fi
        # Проверка основного health
        if curl -s -f http://localhost:5050/health > /dev/null; then
            success "Основной health endpoint доступен"
        else
            warning "Основной health endpoint недоступен"
        fi
        
        # Остановка тестового процесса
        kill $app_pid 2>/dev/null || true
        wait $app_pid 2>/dev/null || true
        
        success "Тестовый запуск завершен успешно"
    else
        error "Приложение не запустилось"
        exit 1
    fi
}

# Создание systemd сервиса
create_systemd_service() {
    log "Создание systemd сервиса..."
    
    cat > /tmp/monitoring-web.service << EOF
[Unit]
Description=Network Monitoring Web Application
After=network.target mysql.service

[Service]
Type=exec
User=$(whoami)
Group=$(whoami)
WorkingDirectory=/opt/monitoring-web
Environment=FLASK_ENV=production
Environment=FLASK_PORT=5050
Environment=FLASK_HOST=0.0.0.0
Environment=PYTHONPATH=/opt/monitoring-web
ExecStart=/usr/bin/python3 run.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF
    
    sudo mv /tmp/monitoring-web.service /etc/systemd/system/
    sudo systemctl daemon-reload
    
    success "Systemd сервис создан"
}

# Финальный запуск
start_application() {
    log "Запуск приложения в продакшн режиме..."
    
    # Остановка старых процессов
    sudo systemctl stop monitoring-web 2>/dev/null || true
    
    # Запуск нового сервиса
    sudo systemctl enable monitoring-web
    sudo systemctl start monitoring-web
    
    # Проверка статуса
    sleep 3
    if sudo systemctl is-active --quiet monitoring-web; then
        success "Приложение запущено как systemd сервис"
        
        # Показать статус
        sudo systemctl status monitoring-web --no-pager -l
        
        # Проверка доступности
        sleep 5
        if curl -s -f http://localhost:5050/api/health > /dev/null; then
            success "Приложение доступно по адресу: http://localhost:5050"
        else
            warning "Приложение запущено, но не отвечает на запросы"
        fi
    else
        error "Не удалось запустить приложение как сервис"
        sudo journalctl -u monitoring-web --no-pager -l
        exit 1
    fi
}

# Показать информацию о развертывании
show_deployment_info() {
    log "Информация о развертывании:"
    echo
    echo "🌐 Веб-интерфейс:"
    echo "   Главная страница:    http://localhost:5050/"
    echo "   VPN мониторинг:      http://localhost:5050/vpn/"
    echo "   RDP мониторинг:      http://localhost:5050/rdp/"
    echo "   SMB мониторинг:      http://localhost:5050/smb/"
    echo
    echo "📡 REST API:"
    echo "   API документация:    http://localhost:5050/api/"
    echo "   Состояние системы (UI): http://localhost:5050/health"
    echo "   Состояние системы (API): http://localhost:5050/api/health"
    echo "   Общий статус:        http://localhost:5050/api/status"
    echo
    echo "🔧 Управление сервисом:"
    echo "   Статус:              sudo systemctl status monitoring-web"
    echo "   Остановка:           sudo systemctl stop monitoring-web"
    echo "   Перезапуск:          sudo systemctl restart monitoring-web"
    echo "   Логи:                sudo journalctl -u monitoring-web -f"
    echo
    echo "📁 Файлы:"
    echo "   Конфигурация:        /etc/infra/config.json"
    echo "   Логи приложения:     /var/log/monitoring-web/app.log"
    echo "   Systemd сервис:      /etc/systemd/system/monitoring-web.service"
    echo
}

# Основная функция
main() {
    echo "════════════════════════════════════════════════════════════════"
    echo "🚀 Развертывание единого приложения мониторинга v2.0.0"
    echo "════════════════════════════════════════════════════════════════"
    echo
    
    check_environment
    echo
    
    install_dependencies
    echo
    
    create_directories
    echo
    
    test_structure
    echo
    
    test_databases
    echo
    
    test_application
    echo
    
    create_systemd_service
    echo
    
    start_application
    echo
    
    show_deployment_info
    
    echo "════════════════════════════════════════════════════════════════"
    success "🎉 Развертывание завершено успешно!"
    echo "════════════════════════════════════════════════════════════════"
}

# Обработка аргументов командной строки
case "${1:-}" in
    "test")
        log "Запуск только тестирования..."
        check_environment
        test_structure
        test_databases
        test_application
        ;;
    "install")
        log "Запуск только установки зависимостей..."
        install_dependencies
        create_directories
        ;;
    "start")
        log "Запуск только приложения..."
        start_application
        ;;
    *)
        main
        ;;
esac
