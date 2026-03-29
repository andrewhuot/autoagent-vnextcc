#!/usr/bin/env bash
# AutoAgent — Stop backend + frontend
# Usage: ./stop.sh

set -euo pipefail

RESET='\033[0m'
DIM='\033[2m'
RED='\033[0;31m'
BOLD_GREEN='\033[1;32m'
BOLD_CYAN='\033[1;36m'
YELLOW='\033[0;33m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PID_FILE="$SCRIPT_DIR/.autoagent/backend.pid"
FRONTEND_PID_FILE="$SCRIPT_DIR/.autoagent/frontend.pid"
BACKEND_PORT=8000
FRONTEND_PORT=5173

echo ""
echo -e "${BOLD_CYAN}  Stopping AutoAgent…${RESET}"
echo ""

stopped=0

stop_pid_file() {
  local file=$1
  local label=$2

  if [[ -f "$file" ]]; then
    local pid
    pid=$(cat "$file")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && echo -e "  ${BOLD_GREEN}✓${RESET}  Stopped $label (pid $pid)"
      stopped=$(( stopped + 1 ))
    else
      echo -e "  ${DIM}ℹ  $label was not running (stale pid $pid)${RESET}"
    fi
    rm -f "$file"
  else
    echo -e "  ${DIM}ℹ  No $label pid file found — trying port…${RESET}"
  fi
}

stop_pid_file "$BACKEND_PID_FILE"  "Backend"
stop_pid_file "$FRONTEND_PID_FILE" "Frontend"

# Fallback: kill by port if pid files weren't found
kill_port() {
  local port=$1
  local label=$2
  local pid
  pid=$(lsof -ti ":$port" 2>/dev/null || true)
  if [[ -n "$pid" ]]; then
    kill "$pid" 2>/dev/null && echo -e "  ${BOLD_GREEN}✓${RESET}  Stopped $label on port $port (pid $pid)"
    stopped=$(( stopped + 1 ))
  fi
}

kill_port $BACKEND_PORT  "Backend"
kill_port $FRONTEND_PORT "Frontend"

echo ""
if [[ $stopped -gt 0 ]]; then
  echo -e "  ${BOLD_GREEN}All processes stopped.${RESET}"
else
  echo -e "  ${DIM}Nothing was running.${RESET}"
fi
echo ""
