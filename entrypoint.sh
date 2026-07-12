#!/bin/bash

# Запуск локального сервера Redis в фоновом режиме (направляем пути в /tmp во избежание ошибок прав доступа на Hugging Face)
echo "Запуск Redis-сервера..."
redis-server --dir /tmp --dbfilename redis-dump.rdb --pidfile /tmp/redis-server.pid --logfile /tmp/redis.log &


# Проверка, что Redis запустился
sleep 2
redis-cli ping

# Запуск Flask-приложения на порту 7860 (дефолтном для Hugging Face Spaces)
echo "Запуск Flask-приложения..."
export PORT=7860
python app.py
