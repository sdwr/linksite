#!/bin/bash
cd /home/sprite/linksite

# --- Backend (FastAPI on port 8000, internal) ---
if [ -f /tmp/linksite.pid ] && kill -0 $(cat /tmp/linksite.pid) 2>/dev/null; then
    echo "Backend already running (PID $(cat /tmp/linksite.pid))"
else
    PORT=8000 nohup python3 main.py > /tmp/linksite.log 2>&1 &
    echo $! > /tmp/linksite.pid
    echo "Backend started (PID $(cat /tmp/linksite.pid)) on port 8000"
fi

# --- Frontend (Next.js on port 8080, public) ---
if [ -f /tmp/linksite-web.pid ] && kill -0 $(cat /tmp/linksite-web.pid) 2>/dev/null; then
    echo "Frontend already running (PID $(cat /tmp/linksite-web.pid))"
else
    cd /home/sprite/linksite/web
    nohup npx next start -p 8080 > /tmp/linksite-web.log 2>&1 &
    echo $! > /tmp/linksite-web.pid
    echo "Frontend started (PID $(cat /tmp/linksite-web.pid)) on port 8080"
fi
