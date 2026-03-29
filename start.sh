#!/usr/bin/env bash
# AutoAgent — Start backend + frontend
# Usage: ./start.sh

set -euo pipefail

# ─── Colors ────────────────────────────────────────────────────────────────────
RESET='\033[0m'
BOLD='\033[1m'
DIM='\033[2m'
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD_WHITE='\033[1;37m'
BOLD_GREEN='\033[1;32m'
BOLD_CYAN='\033[1;36m'

# ─── Helpers ───────────────────────────────────────────────────────────────────
step()  { echo -e "\n${BOLD_CYAN}  ◆ $*${RESET}"; }
ok()    { echo -e "  ${BOLD_GREEN}✓${RESET}  $*"; }
info()  { echo -e "  ${DIM}ℹ  $*${RESET}"; }
warn()  { echo -e "  ${YELLOW}⚠  $*${RESET}"; }
die()   { echo -e "\n  ${RED}✗  Error: $*${RESET}\n"; exit 1; }

hr() {
  echo -e "${DIM}  ──────────────────────────────────────────────────────────${RESET}"
}

# ─── Globals ───────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PID_FILE="$SCRIPT_DIR/.autoagent/backend.pid"
FRONTEND_PID_FILE="$SCRIPT_DIR/.autoagent/frontend.pid"
BACKEND_LOG="$SCRIPT_DIR/.autoagent/backend.log"
FRONTEND_LOG="$SCRIPT_DIR/.autoagent/frontend.log"
BACKEND_PORT=8000
FRONTEND_PORT=5173
BACKEND_URL="http://localhost:$BACKEND_PORT"
FRONTEND_URL="http://localhost:$FRONTEND_PORT"

# ─── Cleanup / Ctrl+C handler ─────────────────────────────────────────────────
cleanup() {
  echo ""
  echo -e "\n  ${YELLOW}Shutting down AutoAgent…${RESET}"

  if [[ -f "$BACKEND_PID_FILE" ]]; then
    local pid
    pid=$(cat "$BACKEND_PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo -e "  ${DIM}Stopped backend (pid $pid)${RESET}"
    fi
    rm -f "$BACKEND_PID_FILE"
  fi

  if [[ -f "$FRONTEND_PID_FILE" ]]; then
    local pid
    pid=$(cat "$FRONTEND_PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo -e "  ${DIM}Stopped frontend (pid $pid)${RESET}"
    fi
    rm -f "$FRONTEND_PID_FILE"
  fi

  echo -e "  ${BOLD_GREEN}Done. See you next time.${RESET}\n"
  exit 0
}

trap cleanup INT TERM

# ─── Checks ────────────────────────────────────────────────────────────────────
banner() {
  echo ""
  echo -e "${BOLD_WHITE}  ┌─────────────────────────────────────────────────────────┐${RESET}"
  echo -e "${BOLD_WHITE}  │                                                         │${RESET}"
  echo -e "${BOLD_WHITE}  │   ${BOLD_CYAN}AutoAgent${RESET}${BOLD_WHITE}  ·  Agent Optimization Platform             │${RESET}"
  echo -e "${BOLD_WHITE}  │   ${DIM}Starting up…${RESET}${BOLD_WHITE}                                            │${RESET}"
  echo -e "${BOLD_WHITE}  │                                                         │${RESET}"
  echo -e "${BOLD_WHITE}  └─────────────────────────────────────────────────────────┘${RESET}"
  echo ""
}

cd "$SCRIPT_DIR"

banner

# Guard: setup must have been run
if [[ ! -d ".venv" ]]; then
  die "Setup hasn't been run yet.\n\n  Run first:  ./setup.sh\n"
fi

# Guard: warn if another instance might be running
if [[ -f "$BACKEND_PID_FILE" ]]; then
  OLD_PID=$(cat "$BACKEND_PID_FILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    warn "Backend already running (pid $OLD_PID). Stop it first: ./stop.sh"
    exit 1
  else
    rm -f "$BACKEND_PID_FILE"
  fi
fi

# Create runtime dir
mkdir -p .autoagent

# Kill any stale processes on our ports
freeport() {
  local port=$1
  local pid
  pid=$(lsof -ti ":$port" 2>/dev/null || true)
  if [[ -n "$pid" ]]; then
    warn "Port $port in use (pid $pid) — killing stale process"
    kill "$pid" 2>/dev/null || true
    sleep 0.5
  fi
}

freeport $BACKEND_PORT
freeport $FRONTEND_PORT

# ─── Activate venv ─────────────────────────────────────────────────────────────
# shellcheck source=/dev/null
source .venv/bin/activate

# ─── Start backend ─────────────────────────────────────────────────────────────
step "Starting backend"

# Load .env if present
if [[ -f ".env" ]]; then
  set -o allexport
  # shellcheck source=/dev/null
  source .env 2>/dev/null || true
  set +o allexport
fi

uvicorn api.server:app \
  --host 127.0.0.1 \
  --port "$BACKEND_PORT" \
  --log-level warning \
  >"$BACKEND_LOG" 2>&1 &

BACKEND_PID=$!
echo "$BACKEND_PID" > "$BACKEND_PID_FILE"
info "Backend process started (pid $BACKEND_PID)"

# ─── Start frontend ────────────────────────────────────────────────────────────
step "Starting frontend"

cd web
npm run dev -- --port "$FRONTEND_PORT" \
  >"$FRONTEND_LOG" 2>&1 &

FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$FRONTEND_PID_FILE"
cd ..
info "Frontend process started (pid $FRONTEND_PID)"

# ─── Wait for health ───────────────────────────────────────────────────────────
step "Waiting for services to be ready"

wait_for_http() {
  local url=$1
  local label=$2
  local max_attempts=30
  local attempt=0
  local chars=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')

  while [[ $attempt -lt $max_attempts ]]; do
    if curl -sf "$url" >/dev/null 2>&1; then
      echo -e "\r  ${BOLD_GREEN}✓${RESET}  $label ready                    "
      return 0
    fi

    local char="${chars[$((attempt % ${#chars[@]}))]}"
    echo -ne "\r  ${DIM}$char  Waiting for ${label}... ($attempt/${max_attempts})${RESET}"
    sleep 1
    attempt=$(( attempt + 1 ))
  done

  echo -e "\r  ${RED}✗  $label did not start within ${max_attempts}s${RESET}"
  local label_lower
  label_lower=$(echo "$label" | tr '[:upper:]' '[:lower:]')
  echo -e "  ${DIM}Check logs: cat .autoagent/${label_lower}.log${RESET}"
  return 1
}

if ! wait_for_http "$BACKEND_URL/api/health" "Backend"; then
  echo -e "\n  ${DIM}Backend log (last 20 lines):${RESET}"
  tail -20 "$BACKEND_LOG" 2>/dev/null | sed 's/^/    /'
  cleanup
  exit 1
fi

if ! wait_for_http "$FRONTEND_URL" "Frontend"; then
  echo -e "\n  ${DIM}Frontend log (last 20 lines):${RESET}"
  tail -20 "$FRONTEND_LOG" 2>/dev/null | sed 's/^/    /'
  cleanup
  exit 1
fi

# ─── Open browser ──────────────────────────────────────────────────────────────
# macOS: open, Linux: xdg-open
if command -v open &>/dev/null; then
  open "$FRONTEND_URL" 2>/dev/null || true
elif command -v xdg-open &>/dev/null; then
  xdg-open "$FRONTEND_URL" 2>/dev/null || true
fi

# ─── Success banner ────────────────────────────────────────────────────────────
echo ""
hr
echo ""
echo -e "  ${BOLD_GREEN}AutoAgent is running!${RESET}"
echo ""
echo -e "  ${BOLD_WHITE}Open in browser:${RESET}"
echo -e "  ${BOLD_CYAN}  Frontend   →  $FRONTEND_URL${RESET}"
echo -e "  ${DIM}  API        →  $BACKEND_URL${RESET}"
echo -e "  ${DIM}  API docs   →  $BACKEND_URL/docs${RESET}"
echo ""
echo -e "  ${DIM}Logs:  .autoagent/backend.log  ·  .autoagent/frontend.log${RESET}"
echo -e "  ${DIM}Stop:  Ctrl+C  or  ./stop.sh${RESET}"
echo ""
hr
echo ""

# ─── Keep alive ────────────────────────────────────────────────────────────────
# Monitor child processes; exit if either dies unexpectedly
while true; do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo -e "\n  ${RED}✗  Backend process died unexpectedly${RESET}"
    echo -e "  ${DIM}Last lines from .autoagent/backend.log:${RESET}"
    tail -10 "$BACKEND_LOG" 2>/dev/null | sed 's/^/    /'
    cleanup
    exit 1
  fi

  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    echo -e "\n  ${RED}✗  Frontend process died unexpectedly${RESET}"
    echo -e "  ${DIM}Last lines from .autoagent/frontend.log:${RESET}"
    tail -10 "$FRONTEND_LOG" 2>/dev/null | sed 's/^/    /'
    cleanup
    exit 1
  fi

  sleep 2
done
