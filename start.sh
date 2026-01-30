#!/bin/bash
cd /home/sprite/linksite
if [ -f /tmp/linksite.pid ] && kill -0 $(cat /tmp/linksite.pid) 2>/dev/null; then
    echo "Already running (PID $(cat /tmp/linksite.pid))"
    exit 0
fi
nohup python3 main.py > /tmp/linksite.log 2>&1 &
echo $! > /tmp/linksite.pid
echo "Started (PID $(cat /tmp/linksite.pid))"
