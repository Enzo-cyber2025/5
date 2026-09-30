#!/bin/bash
set -u
git config user.email "ci@local"
git config user.name "ci"
git checkout -B wl-logs 2>/dev/null || git checkout wl-logs
cp wlh.log wlh.log.last 2>/dev/null || true
git add -f wlh.log wlh.log.last 2>/dev/null
git commit -m "wl log $(date -u +%H%M%S)" 2>&1 | tail -3
git push -f origin wl-logs 2>&1 | tail -5
