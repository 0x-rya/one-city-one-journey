#!/bin/sh
# One City, One Journey (PS-08): multimodal journey planner. Needs only Python 3.9+.
cd "$(dirname "$0")/planner" && PORT="${PORT:-8008}" exec python3 -I server.py
