#!/bin/bash
set -e

echo "[STARTUP $(date)] ========================================"
echo "[STARTUP] Starting Sanarip Med AI container..."
echo "[STARTUP] Python version: $(python --version 2>&1)"
echo "[STARTUP] Port: ${PORT:-7860}"

# Запуск локального сервера Redis в фоновом режиме
echo "[STARTUP] Starting Redis server..."
if command -v redis-server &> /dev/null; then
    nohup redis-server --dir /tmp --dbfilename redis-dump.rdb --pidfile /tmp/redis-server.pid --logfile /tmp/redis.log --daemonize yes > /dev/null 2>&1
    echo "[STARTUP] Redis started, pid: $(cat /tmp/redis-server.pid 2>/dev/null || echo '?')"
else
    echo "[STARTUP] redis-server not found, skipping Redis"
fi

# Проверяем импорт всех модулей
echo "[STARTUP] Testing Python imports..."
python -c "
import sys, os
os.environ['TELEGRAM_BOT_TOKEN'] = 'TEST'
errors = []
modules = ['os', 'json', 'requests', 'flask', 'dotenv', 'telebot', 'psycopg2', 'redis', 'qdrant_client', 'bs4', 'schedule', 'cryptography']
for m in modules:
    try:
        __import__(m)
        print(f'  OK: {m}')
    except ImportError as e:
        errors.append(f'{m}: {e}')
        print(f'  FAIL: {e}')
if errors:
    print(f'[IMPORT ERRORS] {errors}')
    sys.exit(1)
else:
    print('[IMPORT] All modules loaded successfully')
" 2>&1 || echo "[STARTUP] Import test failed, see above"

# Запуск Flask-приложения
export PORT=7860
echo "[STARTUP] Starting Flask app on port $PORT..."
exec python -u app.py 2>&1
