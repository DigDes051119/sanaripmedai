#!/bin/bash

# Запуск локального сервера Redis в фоновом режиме
echo "Запуск Redis-сервера..."
redis-server --daemonize yes

# Проверка, что Redis запустился
sleep 2
redis-cli ping

# Запуск Flask-приложения на порту 7860 (дефолтном для Hugging Face Spaces)
echo "Запуск Flask-приложения..."
export PORT=7860
python app.py
