#!/usr/bin/env python3
"""
Быстрый тест развертывания единого приложения мониторинга
"""

import sys
import os
import time
import requests
import subprocess
from threading import Thread

def test_imports():
    """Тест импортов"""
    print("🔍 Тестирование импортов...")
    try:
        sys.path.append('.')
        from app import create_app
        from app.config import Config
        from app.models.database import db_manager
        print("✅ Импорты: OK")
        return True
    except Exception as e:
        print(f"❌ Ошибка импорта: {e}")
        return False

def test_app_creation():
    """Тест создания приложения"""
    print("🔍 Тестирование создания приложения...")
    try:
        from app import create_app
        from app.config import Config
        
        config = Config()
        app = create_app(config)
        
        with app.app_context():
            blueprints = list(app.blueprints.keys())
            print(f"✅ Приложение создано. Blueprints: {blueprints}")
            return True, app
    except Exception as e:
        print(f"❌ Ошибка создания приложения: {e}")
        return False, None

def test_database_connections():
    """Тест подключений к базам данных"""
    print("🔍 Тестирование подключений к БД...")
    try:
        from app.models.database import db_manager
        
        db_results = {}
        for db_type in ['vpn', 'rdp', 'smb']:
            try:
                with db_manager.get_connection(db_type) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        result = cursor.fetchone()
                        db_results[db_type] = "OK"
                        print(f"✅ {db_type.upper()} база данных: OK")
            except Exception as e:
                db_results[db_type] = f"ERROR: {e}"
                print(f"❌ {db_type.upper()} база данных: {e}")
        
        return all(status == "OK" for status in db_results.values()), db_results
    except Exception as e:
        print(f"❌ Общая ошибка БД: {e}")
        return False, {}

def start_test_server(app):
    """Запуск тестового сервера"""
    print("🚀 Запуск тестового сервера...")
    try:
        app.run(host='127.0.0.1', port=8000, debug=False, threaded=True)
    except Exception as e:
        print(f"❌ Ошибка запуска сервера: {e}")

def test_endpoints():
    """Тест основных endpoints"""
    print("🔍 Тестирование endpoints...")
    
    # Ждем запуска сервера
    time.sleep(3)
    
    endpoints = [
        ('/', 'Главная страница'),
        ('/api/', 'API информация'),
        ('/api/health', 'Health check'),
        ('/vpn/', 'VPN мониторинг'),
        ('/rdp/', 'RDP мониторинг'),
        ('/smb/', 'SMB мониторинг')
    ]
    
    results = {}
    for endpoint, description in endpoints:
        try:
            response = requests.get(f'http://127.0.0.1:8000{endpoint}', timeout=5)
            if response.status_code == 200:
                results[endpoint] = "OK"
                print(f"✅ {description} ({endpoint}): OK")
            else:
                results[endpoint] = f"HTTP {response.status_code}"
                print(f"⚠️ {description} ({endpoint}): HTTP {response.status_code}")
        except Exception as e:
            results[endpoint] = f"ERROR: {e}"
            print(f"❌ {description} ({endpoint}): {e}")
    
    return results

def main():
    """Основная функция тестирования"""
    print("=" * 60)
    print("🚀 Быстрый тест развертывания мониторинга v2.0.0")
    print("=" * 60)
    
    # Тест 1: Импорты
    if not test_imports():
        print("❌ Тест импортов провален. Остановка.")
        return False
    
    # Тест 2: Создание приложения
    app_ok, app = test_app_creation()
    if not app_ok:
        print("❌ Тест создания приложения провален. Остановка.")
        return False
    
    # Тест 3: Базы данных
    db_ok, db_results = test_database_connections()
    if not db_ok:
        print("⚠️ Проблемы с базами данных, но продолжаем тестирование...")
    
    # Тест 4: Запуск сервера и тестирование endpoints
    print("\n🚀 Запуск тестового сервера на 10 секунд...")
    server_thread = Thread(target=start_test_server, args=(app,), daemon=True)
    server_thread.start()
    
    # Тестируем endpoints
    endpoint_results = test_endpoints()
    
    # Результаты
    print("\n" + "=" * 60)
    print("📊 РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ")
    print("=" * 60)
    
    print("\n🔧 Компоненты:")
    print("✅ Импорты: OK")
    print("✅ Создание приложения: OK")
    
    print("\n💾 Базы данных:")
    for db_type, status in db_results.items():
        icon = "✅" if status == "OK" else "❌"
        print(f"{icon} {db_type.upper()}: {status}")
    
    print("\n🌐 Endpoints:")
    for endpoint, status in endpoint_results.items():
        icon = "✅" if status == "OK" else "⚠️" if "HTTP" in status else "❌"
        print(f"{icon} {endpoint}: {status}")
    
    # Общий результат
    total_tests = 2 + len(db_results) + len(endpoint_results)
    passed_tests = 2 + sum(1 for s in db_results.values() if s == "OK") + sum(1 for s in endpoint_results.values() if s == "OK")
    
    print(f"\n📈 Общий результат: {passed_tests}/{total_tests} тестов пройдено")
    
    if passed_tests >= total_tests * 0.8:  # 80% успешности
        print("🎉 РАЗВЕРТЫВАНИЕ УСПЕШНО!")
        print("\n🌐 Приложение готово к использованию:")
        print("   http://localhost:8000/ - Главная страница")
        print("   http://localhost:8000/api/ - API документация")
        return True
    else:
        print("⚠️ РАЗВЕРТЫВАНИЕ С ПРЕДУПРЕЖДЕНИЯМИ")
        print("Некоторые компоненты могут работать неправильно.")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
