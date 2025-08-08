#!/usr/bin/env python3
"""
Тестовый скрипт для проверки базовой структуры приложения
"""

import sys
import os
sys.path.insert(0, '/opt/monitoring-web')

def test_imports():
    """Тестирование импортов модулей"""
    print("🔍 Тестирование импортов...")
    
    try:
        from app.config import Config
        print("✅ Config импортирован успешно")
    except Exception as e:
        print(f"❌ Ошибка импорта Config: {e}")
        return False
    
    try:
        from app.models.database import db_manager
        print("✅ Database manager импортирован успешно")
    except Exception as e:
        print(f"❌ Ошибка импорта Database manager: {e}")
        return False
    
    try:
        from app.utils.filters import pretty_time, rusdatetime
        print("✅ Filters импортированы успешно")
    except Exception as e:
        print(f"❌ Ошибка импорта Filters: {e}")
        return False
    
    try:
        from app.blueprints.main import bp as main_bp
        from app.blueprints.vpn import bp as vpn_bp
        from app.blueprints.rdp import bp as rdp_bp
        from app.blueprints.smb import bp as smb_bp
        from app.blueprints.api import bp as api_bp
        print("✅ Все blueprints импортированы успешно")
    except Exception as e:
        print(f"❌ Ошибка импорта blueprints: {e}")
        return False
    
    return True

def test_config():
    """Тестирование конфигурации"""
    print("\n⚙️ Тестирование конфигурации...")
    
    try:
        from app.config import Config
        config = Config()
        
        print(f"✅ HOST: {config.HOST}")
        print(f"✅ PORT: {config.PORT}")
        print(f"✅ DEBUG: {config.DEBUG}")
        print(f"✅ PATHS доступны: {bool(config.PATHS)}")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка тестирования конфигурации: {e}")
        return False

def test_filters():
    """Тестирование фильтров"""
    print("\n🔧 Тестирование фильтров...")
    
    try:
        from app.utils.filters import pretty_time, rusdatetime, human_filesize
        
        # Тест pretty_time
        result = pretty_time(3661)  # 1 час 1 минута 1 секунда
        print(f"✅ pretty_time(3661) = '{result}'")
        
        # Тест human_filesize
        result = human_filesize(1024*1024)  # 1 МБ
        print(f"✅ human_filesize(1048576) = '{result}'")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка тестирования фильтров: {e}")
        return False

def test_app_creation():
    """Тестирование создания Flask приложения"""
    print("\n🚀 Тестирование создания Flask приложения...")
    
    try:
        from app import create_app
        from app.config import Config
        
        config = Config()
        app = create_app(config)
        
        print(f"✅ Flask приложение создано: {app}")
        print(f"✅ Blueprints зарегистрированы: {len(app.blueprints)}")
        
        # Проверим зарегистрированные blueprints
        for bp_name in app.blueprints:
            print(f"   - {bp_name}")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка создания приложения: {e}")
        return False

def main():
    """Основная функция тестирования"""
    print("🧪 Тестирование базовой структуры приложения мониторинга\n")
    
    tests = [
        test_imports,
        test_config,
        test_filters,
        test_app_creation
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print("=" * 50)
    print(f"📊 Результаты тестирования: {passed}/{total} тестов пройдено")
    
    if passed == total:
        print("🎉 Все тесты пройдены успешно! Базовая структура работает.")
        return True
    else:
        print("⚠️ Некоторые тесты не пройдены. Требуется исправление.")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
