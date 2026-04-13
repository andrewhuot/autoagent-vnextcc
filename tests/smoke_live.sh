#!/usr/bin/env bash
# Live end-to-end CLI smoke test.
#
# Walks the build → eval → optimize loop using a real Gemini key. Skips
# (does not fail) when GOOGLE_API_KEY is unset so this script is safe to
# wire into CI without leaking the secret.
#
# Usage:
#   GOOGLE_API_KEY=... bash tests/smoke_live.sh
#
# Exits 0 on success or skip; 1 on a real failure.

set -e

cd "$(dirname "$0")/.."

if [[ -z "${GOOGLE_API_KEY:-}" ]]; then
  echo "[smoke_live] GOOGLE_API_KEY not set — skipping live smoke test." >&2
  exit 0
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "[smoke_live] jq is required but not installed." >&2
  exit 1
fi

BRIEF="FAQ concierge for B2B SaaS billing and onboarding"
ARTIFACT=".agentlab/build_artifact_latest.json"

step() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
fail() { printf "\033[1;31m✗ %s\033[0m\n" "$*" >&2; exit 1; }
ok()   { printf "\033[1;32m✓ %s\033[0m\n" "$*"; }

step "agentlab doctor"
agentlab doctor || fail "doctor reported an unrecoverable error"
ok "doctor"

step "agentlab build (live LLM expected)"
rm -f "$ARTIFACT"
agentlab build "$BRIEF"
[[ -f "$ARTIFACT" ]] || fail "build did not write $ARTIFACT"
INTENT_COUNT=$(jq '.intents | length' "$ARTIFACT")
[[ "$INTENT_COUNT" -gt 0 ]] || fail "build artifact has no intents"
ok "build produced $INTENT_COUNT intents"

# Confirm the artifact reflects the brief — generic "general_support" alone
# is the loudest sign the LLM path silently fell back.
if jq -e '[.intents[].name] | any(test("billing|onboarding|invoice|subscription|account"; "i"))' "$ARTIFACT" >/dev/null; then
  ok "intents reference the brief domain"
else
  echo "[smoke_live] WARNING: intents do not mention billing/onboarding terms — LLM may have fallen back to pattern matcher" >&2
fi

step "agentlab workbench build"
agentlab workbench build "$BRIEF" || fail "workbench build failed"
ok "workbench build"

step "agentlab eval run"
agentlab eval run || fail "eval run failed"
ok "eval run"

step "agentlab optimize --cycles 1"
agentlab optimize --cycles 1 || fail "optimize cycle failed"
ok "optimize cycle"

printf "\n\033[1;32m✓ live smoke OK\033[0m\n"
