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

elapsed() {
  local END_TIME
  END_TIME=$(date +%s)
  echo $(( END_TIME - START_TIME ))
}

# ─── Main ──────────────────────────────────────────────────────────────────────
banner

echo -e "  ${DIM}This script will:${RESET}"
echo -e "  ${DIM}  [1] Check Python 3.11+ and Node 18+${RESET}"
echo -e "  ${DIM}  [2] Create Python virtual environment${RESET}"
echo -e "  ${DIM}  [3] Install Python dependencies${RESET}"
echo -e "  ${DIM}  [4] Install frontend dependencies${RESET}"
echo -e "  ${DIM}  [5] Copy .env template${RESET}"
echo -e "  ${DIM}  [6] Seed demo data${RESET}"
echo ""
hr

# ─── Step 1: Python version ────────────────────────────────────────────────────
step "Checking Python version"

if ! command -v python3 &>/dev/null; then
  die "Python 3 is not installed.\n\n  Install it from https://python.org/downloads (3.11 or newer required)"
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [[ "$PYTHON_MAJOR" -lt 3 || ( "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 11 ) ]]; then
  die "Python 3.11+ is required, but you have Python $PYTHON_VERSION.\n\n  Download the latest Python from https://python.org/downloads"
fi

ok "Python $PYTHON_VERSION"

# ─── Step 2: Node version ──────────────────────────────────────────────────────
step "Checking Node.js version"

if ! command -v node &>/dev/null; then
  die "Node.js is not installed.\n\n  Install it from https://nodejs.org (v18 or newer required)\n  Tip: use nvm for easy version management: https://github.com/nvm-sh/nvm"
fi

NODE_VERSION=$(node --version | sed 's/v//')
NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d. -f1)

if [[ "$NODE_MAJOR" -lt 18 ]]; then
  die "Node.js 18+ is required, but you have Node $NODE_VERSION.\n\n  Update at https://nodejs.org or via: nvm install 18 && nvm use 18"
fi

ok "Node.js v$NODE_VERSION"

if ! command -v npm &>/dev/null; then
  die "npm is not installed. It should come with Node.js - try reinstalling Node."
fi
ok "npm $(npm --version)"

# ─── Step 3: Python virtual environment ───────────────────────────────────────
step "Setting up Python virtual environment"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -d ".venv" ]]; then
  ok "Virtual environment already exists - skipping creation"
else
  python3 -m venv .venv
  ok "Created .venv"
fi

# Activate
# shellcheck source=/dev/null
source .venv/bin/activate
ok "Activated .venv (Python $(python3 --version | cut -d' ' -f2))"

# ─── Step 4: Python dependencies ──────────────────────────────────────────────
step "Installing Python dependencies"
info "This may take 30-60 seconds on first run..."

if pip install -e '.[dev]' --quiet 2>&1 | tail -3; then
  ok "Python dependencies installed"
else
  # Retry with output visible
  pip install -e '.[dev]' || die "pip install failed. Check the error above."
  ok "Python dependencies installed"
fi

# ─── Step 5: Frontend dependencies ───────────────────────────────────────────
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

# ─── Step 6: Environment file ─────────────────────────────────────────────────
step "Configuring environment"

if [[ -f ".env" ]]; then
  ok ".env already exists - skipping"
else
  cp .env.example .env
  ok "Created .env from .env.example"
  warn "Add your API keys to .env for full functionality (or leave blank for mock mode)"
fi

# ─── Step 7: Seed demo data ───────────────────────────────────────────────────
step "Seeding demo data"
info "Loading synthetic conversations, traces, and optimization history..."

# Make sure venv is active
source .venv/bin/activate

if python3 -c "
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

# ─── Done ──────────────────────────────────────────────────────────────────────
TOTAL=$(elapsed)

echo ""
hr
echo ""
echo -e "  ${BOLD_GREEN}✓  Setup complete in ${TOTAL}s${RESET}"
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
