#!/usr/bin/env bash
# AutoAgent - First-time setup
# Usage: ./setup.sh

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
WHITE='\033[0;37m'
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

banner() {
  echo ""
  echo -e "${BOLD_WHITE}  ┌─────────────────────────────────────────────────────────┐${RESET}"
  echo -e "${BOLD_WHITE}  │                                                         │${RESET}"
  echo -e "${BOLD_WHITE}  │   ${BOLD_CYAN}AutoAgent${RESET}${BOLD_WHITE}  -  Agent Optimization Platform             │${RESET}"
  echo -e "${BOLD_WHITE}  │   ${DIM}First-time setup${RESET}${BOLD_WHITE}                                        │${RESET}"
  echo -e "${BOLD_WHITE}  │                                                         │${RESET}"
  echo -e "${BOLD_WHITE}  └─────────────────────────────────────────────────────────┘${RESET}"
  echo ""
}

# ─── Timer ─────────────────────────────────────────────────────────────────────
START_TIME=$(date +%s)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_BIN_DIR="$VENV_DIR/bin"
VENV_ACTIVATE="$VENV_BIN_DIR/activate"
VENV_PYTHON="$VENV_BIN_DIR/python"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11
PYTHON_CANDIDATES=(python3.12 python3.13 python3.14 python3.11 python3)

elapsed() {
  local END_TIME
  END_TIME=$(date +%s)
  echo $(( END_TIME - START_TIME ))
}

activate_venv() {
  if [[ ! -f "$VENV_ACTIVATE" ]]; then
    die "Virtual environment activation script not found at $VENV_ACTIVATE.\n\n  Remove .venv and rerun ./setup.sh"
  fi

  if [[ ! -x "$VENV_PYTHON" ]]; then
    die "Virtual environment Python not found at $VENV_PYTHON.\n\n  Remove .venv and rerun ./setup.sh"
  fi

  # shellcheck source=/dev/null
  source "$VENV_ACTIVATE"
}

minimum_python_requirement() {
  printf '%s.%s' "$MIN_PYTHON_MAJOR" "$MIN_PYTHON_MINOR"
}

# Prefer explicit Homebrew-style Python commands before the generic python3 so
# macOS does not accidentally pick the older system interpreter.
python_version_for_command() {
  local python_command
  python_command="$1"
  "$python_command" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null
}

python_command_is_compatible() {
  local python_command
  local python_version
  local python_major
  local python_minor
  python_command="$1"
  python_version=$(python_version_for_command "$python_command") || return 1
  python_major=$(printf '%s\n' "$python_version" | cut -d. -f1)
  python_minor=$(printf '%s\n' "$python_version" | cut -d. -f2)

  [[ -n "$python_major" ]] || return 1
  [[ -n "$python_minor" ]] || return 1

  if [[ "$python_major" -gt "$MIN_PYTHON_MAJOR" ]]; then
    return 0
  fi

  if [[ "$python_major" -eq "$MIN_PYTHON_MAJOR" && "$python_minor" -ge "$MIN_PYTHON_MINOR" ]]; then
    return 0
  fi

  return 1
}

python_search_order() {
  local ordered_commands
  local python_command
  ordered_commands=""

  for python_command in "${PYTHON_CANDIDATES[@]}"; do
    if [[ -n "$ordered_commands" ]]; then
      ordered_commands="${ordered_commands}, "
    fi
    ordered_commands="${ordered_commands}${python_command}"
  done

  printf '%s\n' "$ordered_commands"
}

find_compatible_python() {
  local python_command

  for python_command in "${PYTHON_CANDIDATES[@]}"; do
    if ! command -v "$python_command" >/dev/null 2>&1; then
      continue
    fi

    if python_command_is_compatible "$python_command"; then
      printf '%s\n' "$python_command"
      return 0
    fi
  done

  return 1
}

select_compatible_python_or_die() {
  local selected_python
  selected_python=$(find_compatible_python) && {
    printf '%s\n' "$selected_python"
    return 0
  }

  die "Python $(minimum_python_requirement)+ is required, but no compatible interpreter was found on PATH.\n\n  setup.sh checked: $(python_search_order)\n  Install one with Homebrew: brew install python@3.12\n  Then re-run ./setup.sh"
}

main() {
  local python_command
  local python_version
  local node_version
  local node_major
  local total

  banner

  echo -e "  ${DIM}This script will:${RESET}"
  echo -e "  ${DIM}  [1] Check Python $(minimum_python_requirement)+ and Node 18+${RESET}"
  echo -e "  ${DIM}  [2] Create Python virtual environment${RESET}"
  echo -e "  ${DIM}  [3] Install Python dependencies${RESET}"
  echo -e "  ${DIM}  [4] Install frontend dependencies${RESET}"
  echo -e "  ${DIM}  [5] Copy .env template${RESET}"
  echo -e "  ${DIM}  [6] Seed demo data${RESET}"
  echo ""
  hr

  # ─── Step 1: Python version ──────────────────────────────────────────────────
  step "Checking Python version"

  python_command=$(select_compatible_python_or_die)
  python_version=$(python_version_for_command "$python_command")

  ok "$python_command ($python_version)"

  # ─── Step 2: Node version ────────────────────────────────────────────────────
  step "Checking Node.js version"

  if ! command -v node &>/dev/null; then
    die "Node.js is not installed.\n\n  Install it from https://nodejs.org (v18 or newer required)\n  Tip: use nvm for easy version management: https://github.com/nvm-sh/nvm"
  fi

  node_version=$(node --version | sed 's/v//')
  node_major=$(printf '%s\n' "$node_version" | cut -d. -f1)

  if [[ "$node_major" -lt 18 ]]; then
    die "Node.js 18+ is required, but you have Node $node_version.\n\n  Update at https://nodejs.org or via: nvm install 18 && nvm use 18"
  fi

  ok "Node.js v$node_version"

  if ! command -v npm &>/dev/null; then
    die "npm is not installed. It should come with Node.js - try reinstalling Node."
  fi
  ok "npm $(npm --version)"

  # ─── Step 3: Python virtual environment ─────────────────────────────────────
  step "Setting up Python virtual environment"

  cd "$SCRIPT_DIR"

  if [[ -d "$VENV_DIR" ]]; then
    ok "Virtual environment already exists - skipping creation"
  else
    "$python_command" -m venv "$VENV_DIR"
    ok "Created .venv"
  fi

  # Activate
  activate_venv
  ok "Activated .venv (Python $("$VENV_PYTHON" --version | cut -d' ' -f2))"

  # ─── Step 4: Python dependencies ────────────────────────────────────────────
  step "Installing Python dependencies"
  info "This may take 30-60 seconds on first run..."
  info "Upgrading pip, setuptools, and wheel inside .venv..."

  "$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel >/dev/null

  if "$VENV_PYTHON" -m pip install -e '.[dev]' --quiet 2>&1 | tail -3; then
    ok "Python dependencies installed"
  else
    # Retry with output visible
    "$VENV_PYTHON" -m pip install -e '.[dev]' || die "pip install failed. Check the error above."
    ok "Python dependencies installed"
  fi

  if "$VENV_PYTHON" -c "import uvicorn" >/dev/null 2>&1; then
    ok "Verified uvicorn is importable from .venv"
  else
    die "uvicorn is not importable from .venv after install.\n\n  Re-run ./setup.sh and inspect the pip output above."
  fi

  # ─── Step 5: Frontend dependencies ─────────────────────────────────────────
  step "Installing frontend dependencies"
  info "This may take 30-60 seconds on first run..."

  if [[ ! -d "web" ]]; then
    die "web/ directory not found. Are you in the project root?"
  fi

  cd web
  if npm install --silent 2>/dev/null; then
    ok "Frontend dependencies installed"
  else
    npm install || die "npm install failed. Check the error above."
    ok "Frontend dependencies installed"
  fi
  cd ..

  # ─── Step 6: Environment file ───────────────────────────────────────────────
  step "Configuring environment"

  if [[ -f ".env" ]]; then
    ok ".env already exists - skipping"
  else
    cp .env.example .env
    ok "Created .env from .env.example"
    warn "Add your API keys to .env for full functionality (or leave blank for mock mode)"
  fi

  # ─── Step 7: Seed demo data ─────────────────────────────────────────────────
  step "Seeding demo data"
  info "Loading synthetic conversations, traces, and optimization history..."

  # Make sure venv is active
  activate_venv

  if "$VENV_PYTHON" -c "
import sys, os
sys.path.insert(0, '.')
os.environ.setdefault('AUTOAGENT_USE_MOCK', 'true')
vp_seeded = False
builder_seeded = False

try:
    from evals.vp_demo_data import seed_demo_data
    from evals.vp_demo_data import seed_trace_demo_data, seed_optimization_history
    result = seed_demo_data()
    trace_result = seed_trace_demo_data()
    memory_result = seed_optimization_history()
    print(f'  Seeded {result} VP demo conversations')
    print(f'  Seeded {trace_result} trace events')
    print(f'  Seeded {memory_result} optimization history entries')
    vp_seeded = True
except Exception as e:
    print(f'  VP demo: {e}', file=sys.stderr)

try:
    from builder.demo_data import seed_builder_demo
    from builder.store import BuilderStore
    store = BuilderStore()
    seed_builder_demo(store)
    print('  Builder demo data loaded')
    builder_seeded = True
except Exception as e:
    print(f'  Builder demo: {e}', file=sys.stderr)

if not (vp_seeded and builder_seeded):
    raise SystemExit(1)
" 2>&1; then
    ok "Demo data seeded"
  else
    warn "Demo data seeding had warnings (non-fatal; app will still run)"
  fi

  # ─── Done ────────────────────────────────────────────────────────────────────
  total=$(elapsed)

  echo ""
  hr
  echo ""
  echo -e "  ${BOLD_GREEN}✓  Setup complete in ${total}s${RESET}"
  echo ""
  echo -e "  ${BOLD_WHITE}What's next:${RESET}"
  echo ""
  echo -e "  ${BOLD_CYAN}  ./start.sh${RESET}          Start AutoAgent (backend + frontend)"
  echo -e "  ${DIM}  make start${RESET}           Same thing, via Make"
  echo ""
  echo -e "  ${DIM}  Edit .env to add API keys for live optimization${RESET}"
  echo -e "  ${DIM}  Or leave blank to run in mock mode (no keys needed)${RESET}"
  echo ""
  hr
  echo ""
}

# Keep the script sourceable for tests so interpreter selection can be exercised
# without running the full setup flow.
if [[ "${AUTOAGENT_SETUP_SOURCE_ONLY:-0}" != "1" ]]; then
  main "$@"
fi
