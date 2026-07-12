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

# Запускаем Telegram бота в фоне (не через exec, чтобы контейнер не умер при падении)
echo "[STARTUP] Starting Telegram bot (telegram_bot.py)..."
python -u telegram_bot.py 2>&1 &
BOT_PID=$!
echo "[STARTUP] Bot PID: $BOT_PID."

# Бесконечный цикл: если бот падает — перезапускаем его
while true; do
    if ! kill -0 $BOT_PID 2>/dev/null; then
        echo "[STARTUP $(date)] Bot process died. Restarting in 3 seconds..."
        sleep 3
        python -u telegram_bot.py 2>&1 &
        BOT_PID=$!
        echo "[STARTUP $(date)] New Bot PID: $BOT_PID."
    fi
    # Проверяем сервер раз в 30 секунд
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        echo "[STARTUP $(date)] Server process died. Restarting..."
        python -u server.py &
        SERVER_PID=$!
    fi
    sleep 5
done
