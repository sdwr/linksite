#!/bin/bash
cd /home/sprite/linksite
set -a
source .env
set +a
exec python3 main.py
