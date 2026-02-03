#!/bin/bash
# Stop linksite app

if [ -f /tmp/linksite.pid ]; then
    PID=$(cat /tmp/linksite.pid)
    if kill -0 $PID 2>/dev/null; then
        kill -9 $PID
        echo "Stopped app (PID $PID)"
    fi
    rm -f /tmp/linksite.pid
fi

# Also kill any stray python processes running main.py
pkill -9 -f "python3 main.py" 2>/dev/null

echo "App stopped"
