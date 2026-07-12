#!/bin/bash
set -e

echo "[STARTUP] Starting Sanarip Med AI container..."

# Запуск локального сервера Redis в фоновом режиме
echo "[STARTUP] Starting Redis server..."
if command -v redis-server &> /dev/null; then
    redis-server --dir /tmp --dbfilename redis-dump.rdb --pidfile /tmp/redis-server.pid --logfile /tmp/redis.log &
    sleep 2
    redis-cli ping && echo "[STARTUP] Redis is alive" || echo "[STARTUP] Redis ping failed (non-fatal)"
else
    echo "[STARTUP] redis-server not found, skipping Redis"
fi

# Запуск Flask-приложения на порту 7860
echo "[STARTUP] Starting Flask app on port 7860..."
export PORT=7860
exec python -u app.py
