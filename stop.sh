#!/bin/bash
# Stop backend
if [ -f /tmp/linksite.pid ]; then
    kill $(cat /tmp/linksite.pid) 2>/dev/null && echo "Backend stopped" || echo "Backend not running"
    rm -f /tmp/linksite.pid
else
    echo "Backend stopped (no PID file)"
fi

# Stop frontend
if [ -f /tmp/linksite-web.pid ]; then
    kill $(cat /tmp/linksite-web.pid) 2>/dev/null && echo "Frontend stopped" || echo "Frontend not running"
    rm -f /tmp/linksite-web.pid
else
    echo "Frontend stopped (no PID file)"
fi
