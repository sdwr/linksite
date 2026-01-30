#!/bin/bash
if [ -f /tmp/linksite.pid ]; then
    PID=$(cat /tmp/linksite.pid)
    kill $PID 2>/dev/null
    rm /tmp/linksite.pid
    echo "Stopped (PID $PID)"
else
    # Try to find it anyway
    pkill -f 'python3 main.py' 2>/dev/null
    echo "Stopped (no PID file)"
fi
