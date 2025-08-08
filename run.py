#!/usr/bin/env python3
"""
Точка входа для запуска объединённого приложения мониторинга
"""

import os
import sys
import logging
from app import create_app
from app.config import Config

def setup_logging():
    """Настройка логирования"""
    log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('/var/log/monitoring-web/app.log', mode='a')
        ]
    )

def main():
    """Главная функция запуска приложения"""
    try:
        # Создание директории для логов
        os.makedirs('/var/log/monitoring-web', exist_ok=True)
        
        # Настройка логирования
        setup_logging()
        logger = logging.getLogger(__name__)
        
        # Создание приложения
        config = Config()
        app = create_app(config)
        
        logger.info("Запуск объединённого приложения мониторинга")
        logger.info(f"Host: {config.HOST}, Port: {config.PORT}")
        logger.info(f"Debug режим: {config.DEBUG}")
        
        # Запуск приложения
        app.run(
            host=config.HOST,
            port=config.PORT,
            debug=config.DEBUG,
            threaded=True
        )
        
    except Exception as e:
        print(f"Ошибка запуска приложения: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
