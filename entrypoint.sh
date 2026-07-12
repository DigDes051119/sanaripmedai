#!/bin/bash

echo "[STARTUP $(date)] ========================================"
echo "[STARTUP] Starting Sanarip Med AI container..."
echo "[STARTUP] Python: $(python --version 2>&1)"

export PORT=7860

# Запускаем health-check сервер в фоне (нужен HF Spaces для проверки жизни контейнера)
echo "[STARTUP] Starting health-check server (server.py) on port $PORT..."
python -u server.py &
SERVER_PID=$!
sleep 1

# Проверяем, что health-check сервер запустился
if kill -0 $SERVER_PID 2>/dev/null; then
    echo "[STARTUP] Health-check server running (PID: $SERVER_PID)."
else
    echo "[STARTUP] WARNING: Health-check server failed to start."
fi

echo "[STARTUP] Starting Telegram bot (telegram_bot.py)..."
exec python -u telegram_bot.py 2>&1
