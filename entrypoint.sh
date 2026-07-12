#!/bin/bash

echo "[STARTUP $(date)] ========================================"
echo "[STARTUP] Starting Sanarip Med AI container..."
echo "[STARTUP] Python: $(python --version 2>&1)"
echo "[STARTUP] Flask: $(python -c 'import flask;print(flask.__version__)' 2>&1)"

export PORT=7860

echo "[STARTUP] Starting minimal Flask app on port $PORT..."
exec python -u app.py 2>&1
