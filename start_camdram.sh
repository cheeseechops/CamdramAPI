#!/bin/bash
# Start CamDram API/UI for Jarvis (proxied at /visage/camdram/)
# Usage: ./start_camdram.sh [port]

cd "$(dirname "$0")"
PORT=${1:-5002}
export PORT

# Prefer venv if present (same as other Jarvis Python apps)
if [ -d /home/visage/venv_py311 ]; then
  source /home/visage/venv_py311/bin/activate
fi

exec python3 application.py
