#!/bin/sh
# macOS/Linux: ./start-board.sh  (stop: ./start-board.sh --stop)
cd "$(dirname "$0")" && exec python3 launch.py "$@"
