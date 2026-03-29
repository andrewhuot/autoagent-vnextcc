#!/usr/bin/env bash
# AutoAgent - Stop backend + frontend
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
echo -e "${BOLD_CYAN}  Stopping AutoAgent...${RESET}"
echo ""

stopped=0

stop_pid_file() {
  local file="${1-}"
  local label="${2-}"
  if [[ -z "$file" || -z "$label" ]]; then
    echo -e "  ${RED}✗  Internal error: stop_pid_file requires FILE and LABEL${RESET}" >&2
    return 1
  fi

  if [[ -f "$file" ]]; then
    local pid
    pid=$(cat "$file")
    if kill -0 "$pid" 2>/dev/null; then
      if kill "$pid" 2>/dev/null; then
        echo -e "  ${BOLD_GREEN}✓${RESET}  Stopped ${label} (pid ${pid})"
        stopped=$(( stopped + 1 ))
      fi
    else
      echo -e "  ${DIM}ℹ  ${label} was not running (stale pid ${pid})${RESET}"
    fi
    rm -f "$file"
  else
    echo -e "  ${DIM}ℹ  No ${label} pid file found - trying port...${RESET}"
  fi
}

stop_pid_file "$BACKEND_PID_FILE"  "Backend"
stop_pid_file "$FRONTEND_PID_FILE" "Frontend"

# Fallback: only stop processes that look like AutoAgent services.
is_autoagent_backend_process() {
  local command_line="${1-}"
  [[ "$command_line" == *"api.server:app"* ]]
}

is_autoagent_frontend_process() {
  local command_line="${1-}"
  [[ "$command_line" == *"vite"* ]] || [[ "$command_line" == *"npm run dev"* ]]
}

kill_port() {
  local port="${1-}"
  local label="${2-}"
  local kind="${3-}"
  if [[ -z "$port" || -z "$label" || -z "$kind" ]]; then
    echo -e "  ${RED}✗  Internal error: kill_port requires PORT, LABEL, and KIND${RESET}" >&2
    return 1
  fi
  local pid
  pid=$(lsof -ti ":$port" 2>/dev/null || true)
  if [[ -n "$pid" ]]; then
    local command_line
    command_line=$(ps -p "$pid" -o command= 2>/dev/null || true)

    if [[ "$kind" == "backend" ]] && is_autoagent_backend_process "$command_line"; then
      if kill "$pid" 2>/dev/null; then
        echo -e "  ${BOLD_GREEN}✓${RESET}  Stopped ${label} on port ${port} (pid ${pid})"
        stopped=$(( stopped + 1 ))
      fi
      return
    fi

    if [[ "$kind" == "frontend" ]] && is_autoagent_frontend_process "$command_line"; then
      if kill "$pid" 2>/dev/null; then
        echo -e "  ${BOLD_GREEN}✓${RESET}  Stopped ${label} on port ${port} (pid ${pid})"
        stopped=$(( stopped + 1 ))
      fi
      return
    fi

    echo -e "  ${DIM}ℹ  Leaving ${label} port ${port} alone (pid ${pid} does not look like AutoAgent)${RESET}"
  fi
}

kill_port $BACKEND_PORT  "Backend" "backend"
kill_port $FRONTEND_PORT "Frontend" "frontend"

echo ""
if [[ $stopped -gt 0 ]]; then
  echo -e "  ${BOLD_GREEN}All processes stopped.${RESET}"
else
  echo -e "  ${DIM}Nothing was running.${RESET}"
fi
echo ""
