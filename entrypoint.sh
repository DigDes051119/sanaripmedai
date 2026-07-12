#!/bin/bash

echo "[STARTUP $(date)] ========================================"
echo "[STARTUP] Starting Sanarip Med AI container..."
echo "[STARTUP] Python: $(python --version 2>&1)"

export PORT=7860

# Запуск локального Redis-сервера
echo "[STARTUP] Starting local Redis server..."
redis-server --daemonize yes

# Запуск основного Flask веб-сервера (обслуживает и вебхуки, и healthcheck)
echo "[STARTUP] Starting Flask / Webhook server (app.py) on port $PORT..."

python -u app.py 2>&1 &
APP_PID=$!

echo "[STARTUP] Server PID: $APP_PID."

# Бесконечный цикл контроля процесса
while true; do
    if ! kill -0 $APP_PID 2>/dev/null; then
        echo "[STARTUP $(date)] Flask server process died. Restarting in 3 seconds..."
        sleep 3
        python -u app.py 2>&1 &
        APP_PID=$!
        echo "[STARTUP $(date)] New Flask server PID: $APP_PID."
    fi
    sleep 5
done

