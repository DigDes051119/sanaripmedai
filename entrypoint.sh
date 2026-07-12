#!/bin/bash

echo "[STARTUP $(date)] ========================================"
echo "[STARTUP] Starting Sanarip Med AI container..."
echo "[STARTUP] Python: $(python --version 2>&1)"
echo "[STARTUP] Port: 7860"

export PORT=7860

# Start Redis in background (best-effort)
echo "[STARTUP] Redis: $(command -v redis-server || echo 'not found')"
if command -v redis-server &>/dev/null; then
    nohup redis-server --dir /tmp --dbfilename redis-dump.rdb --pidfile /tmp/redis-server.pid --logfile /tmp/redis.log --daemonize yes > /dev/null 2>&1 &
fi

# Test critical imports
echo "[STARTUP] Testing imports..."
python -c "
import sys
modules = ['flask', 'requests', 'dotenv', 'telebot', 'psycopg2', 'redis', 'qdrant_client', 'bs4', 'schedule', 'cryptography']
for m in modules:
    try:
        __import__(m)
        print(f'  OK: {m}')
    except ImportError as e:
        print(f'  FAIL: {m} -> {e}')
        sys.stdout.flush()
print('[STARTUP] Import test complete')
" 2>&1

echo "[STARTUP] Starting Flask..."
python -u app.py 2>&1
