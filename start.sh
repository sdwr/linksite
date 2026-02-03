#!/bin/bash
cd /home/sprite/linksite

# Kill any existing python processes first
pkill -9 -f "python3 main.py" 2>/dev/null

# Start the app
if [ -f /tmp/linksite.pid ] && kill -0 $(cat /tmp/linksite.pid) 2>/dev/null; then
    echo "App already running (PID $(cat /tmp/linksite.pid))"
else
    nohup python3 main.py > /tmp/linksite.log 2>&1 &
    echo $! > /tmp/linksite.pid
    sleep 2
    if kill -0 $(cat /tmp/linksite.pid) 2>/dev/null; then
        echo "App started (PID $(cat /tmp/linksite.pid)) on port 8080"
    else
        echo "App failed to start - check /tmp/linksite.log"
        exit 1
    fi
fi
