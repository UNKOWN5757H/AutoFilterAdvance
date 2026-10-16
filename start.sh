#!/bin/bash
set -e
if [ -z "$UPSTREAM_REPO" ]; then
  echo "Cloning main Repository..."
  git clone https://github.com/UNKOWN5757H/AutoFilterAdvance /AutoFilterAdvance
else
  echo "Cloning Custom Repo from $UPSTREAM_REPO..."
  git clone "$UPSTREAM_REPO" /AutoFilterAdvance
fi
cd /AutoFilterAdvance
pip3 install --no-cache-dir -U -r requirements.txt
echo "Starting Bot..."
exec python3 bot.py
