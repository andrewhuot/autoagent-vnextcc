# VP-Ready Demo Brief — Make AutoAgent Unforgettable in 5 Minutes

## Mission
Create a polished, rehearsed, VP-ready demo flow that showcases AutoAgent's full power in under 5 minutes. The demo should tell a STORY — not just show features. A VP should walk away thinking "we need this."

## The Story Arc
```
Act 1: "Here's your broken agent" (30s)
Act 2: "Watch AutoAgent diagnose the problems" (60s)  
Act 3: "Watch it fix itself" (90s)
Act 4: "Here's what changed — you approve it" (60s)
Act 5: "Deploy with one click" (30s)
```

## What to Build

### 1. `autoagent demo vp` Command
A new demo subcommand specifically designed for VP presentations:

```bash
autoagent demo vp [--agent-name "Acme Support Bot"] [--company "Acme Corp"]
```

This should:

**Act 1 — The Broken Agent (dramatic reveal)**
- Initialize with a pre-crafted "bad" synthetic dataset — NOT random failures, but a carefully designed scenario:
  - An e-commerce support bot for "{company}" 
  - 40% of billing queries get misrouted to tech support
  - 3 safety violations where the bot leaked internal pricing
  - Response latency averaging 4.5s (SLA is 3s)
  - Customer satisfaction at 62% (target: 85%)
- Print a dramatic health report with RED indicators:
  ```
  ⚠️  Agent Health Report: Acme Support Bot
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  
  Overall Score: 0.62 ■■■■■■░░░░ CRITICAL
  
  🔴 Routing Accuracy:  58%  (40% of billing → wrong agent)
  🔴 Safety Score:       0.94 (3 data leaks detected)
  🔴 Avg Latency:        4.5s (SLA: 3.0s)
  🟡 Resolution Rate:    71%
  🟢 Tone & Empathy:     0.89
  
  Top Issues:
    1. 🔴 Billing queries routed to tech_support (23 conversations)
    2. 🔴 Internal pricing exposed to customers (3 conversations)
    3. 🟡 Tool timeout on order_lookup (8 conversations)
  ```

**Act 2 — Diagnosis (the "aha" moment)**
- Run the observer and print findings with storytelling:
  ```
  🔍 Diagnosing issues...
  
  Root Cause Analysis:
  ┌─────────────────────────────────────────────────────────┐
  │ Issue #1: Billing Misroutes (CRITICAL)                  │
  │ The routing instructions lack keywords for billing      │
  │ terms like "invoice", "charge", "refund", "payment".    │
  │ These queries fall through to the default tech_support   │
  │ agent instead of billing_agent.                         │
  │                                                         │
  │ Impact: 23 misrouted conversations → frustrated users   │
  │ Fix confidence: HIGH                                    │
  ├─────────────────────────────────────────────────────────┤
  │ Issue #2: Data Leak in Safety Policy (CRITICAL)         │
  │ The safety instructions don't classify internal         │
  │ pricing tiers as confidential data. The bot responds    │
  │ to "what's your enterprise pricing?" with internal      │
  │ rate cards.                                             │
  │                                                         │
  │ Impact: 3 data leaks → compliance risk                  │
  │ Fix confidence: HIGH                                    │
  ├─────────────────────────────────────────────────────────┤
  │ Issue #3: Tool Latency (MODERATE)                       │
  │ order_lookup tool timeout is set to 10s. Most calls     │
  │ complete in 2s but timeout causes 4.5s average.         │
  │                                                         │
  │ Impact: 8 slow conversations → poor user experience     │
  │ Fix confidence: MEDIUM                                  │
  └─────────────────────────────────────────────────────────┘
  ```

**Act 3 — Self-Healing (the "wow" moment)**
- Run 3 optimization cycles with rich streaming output:
  ```
  ⚡ Optimizing... (3 cycles)
  
  Cycle 1/3: Fixing billing routing
    ↳ Adding keywords: "invoice", "charge", "refund", "payment", "billing"
    ↳ Evaluating... score: 0.62 → 0.74 (+0.12) ✨
    ↳ ✅ Accepted — 19 fewer misroutes
  
  Cycle 2/3: Hardening safety policy  
    ↳ Adding "internal pricing" to confidential data list
    ↳ Adding refusal template for enterprise rate requests
    ↳ Evaluating... score: 0.74 → 0.81 (+0.07) ✨
    ↳ ✅ Accepted — 3 data leaks → 0
  
  Cycle 3/3: Tuning tool latency
    ↳ Reducing order_lookup timeout from 10s to 4s
    ↳ Adding retry with exponential backoff
    ↳ Evaluating... score: 0.81 → 0.87 (+0.06) ✨
    ↳ ✅ Accepted — avg latency 4.5s → 2.1s
  ```
- Add brief pauses between phases (0.5-1s) for dramatic effect using `time.sleep()`
- Each cycle should feel like watching a surgeon operate

**Act 4 — Review & Approve (the "trust" moment)**
- Print the change cards in a clean format:
  ```
  📋 Changes for Review
  ━━━━━━━━━━━━━━━━━━━━
  
  Change 1: Routing Keywords Update
  ┌──────────────────────────────────────────┐
  │ routing.rules[billing_agent].keywords    │
  │                                          │
  │ - ["billing", "account", "subscription"] │
  │ + ["billing", "account", "subscription", │
  │ +  "invoice", "charge", "refund",        │
  │ +  "payment", "receipt", "credit"]       │
  │                                          │
  │ Score: 0.62 → 0.74 (+19%)               │
  │ Confidence: p=0.001 (very high)          │
  └──────────────────────────────────────────┘
  
  Change 2: Safety Policy Hardening
  ┌──────────────────────────────────────────┐
  │ instructions.safety.confidential_data    │
  │                                          │
  │ + "internal_pricing_tiers"               │
  │ + "enterprise_rate_cards"                │
  │ + "partner_discount_schedules"           │
  │                                          │
  │ Safety: 0.94 → 1.00 (zero violations)   │
  │ Confidence: p=0.003 (high)               │
  └──────────────────────────────────────────┘
  
  Change 3: Tool Timeout Optimization
  ┌──────────────────────────────────────────┐
  │ tools.order_lookup.timeout_seconds       │
  │                                          │
  │ - 10                                     │
  │ + 4                                      │
  │                                          │
  │ tools.order_lookup.retry.enabled         │
  │                                          │
  │ - false                                  │
  │ + true                                   │
  │                                          │
  │ Latency: 4.5s → 2.1s (-53%)             │
  │ Confidence: p=0.01 (high)                │
  └──────────────────────────────────────────┘
  ```

**Act 5 — The Result (the "close" moment)**
- Print a before/after comparison:
  ```
  ✦ Results
  ━━━━━━━━━
  
                    Before    After     Change
  Overall Score     0.62      0.87      +40% ✨
  Routing Accuracy  58%       94%       +62%
  Safety Score      0.94      1.00      +6%
  Avg Latency       4.5s      2.1s      -53%
  Resolution Rate   71%       88%       +24%
  
  🎯 All 3 critical issues resolved in 3 optimization cycles.
  
  Next steps:
    autoagent server    → Open web console to explore details
    autoagent cx deploy → Deploy to CX Agent Studio
    autoagent replay    → See full optimization history
  ```

### 2. Curated Synthetic Data for VP Demo
Create `evals/vp_demo_data.py` — a module with hand-crafted conversations that tell a compelling story:
- 15 billing misroute conversations (user asks about invoice, gets tech support response)
- 3 safety violation conversations (bot reveals internal pricing)
- 8 high-latency conversations (tool timeouts)
- 10 successful conversations (to show the agent isn't completely broken)
- 5 quality issue conversations (vague or unhelpful responses)

Each conversation should have:
- Realistic multi-turn dialogue (not just "User: X, Bot: Y")
- Named users ("Sarah M.", "James K.") for realism
- Specific product references ("Order #A1234", "Pro Plan")
- Emotional arc (frustration → escalation in failure cases)

### 3. VP Demo Script in README
Add a "VP Demo" section to the README with:
- What to say at each step (presenter script)
- Expected output at each step
- Talking points for each "wow" moment
- How to transition to the web console
- FAQ / objection handling

### 4. `autoagent demo vp --web` Flag
When `--web` is passed:
- After the CLI demo completes, auto-start the server
- Auto-open the web console
- The Dashboard should show the optimization journey from the demo
- The presenter can then click through changes, explore traces, show the blame map

## Implementation Notes
- The VP demo should be DETERMINISTIC — same output every time (use fixed seeds)
- Use `time.sleep()` for dramatic pauses (configurable with `--no-pause` flag for testing)
- All CLI output should be crafted for maximum visual impact — this is a PRESENTATION
- The curated conversations should feel real enough that a VP doesn't question them
- Test the full flow end-to-end

## Files to Create/Modify
- CREATE: `evals/vp_demo_data.py` (~400 lines, curated conversations)
- CREATE: `tests/test_vp_demo.py` (~50 lines)
- MODIFY: `runner.py` (add `demo vp` subcommand)
- MODIFY: `README.md` (add VP Demo section)

## Quality Bar
- `python3 -m pytest tests/ -x -q` must pass
- The VP demo must run cleanly end-to-end: `autoagent demo vp --no-pause`
- README demo section must be clear and actionable
- Commit and push to master

## When Done
Commit: `feat: VP-ready demo — curated scenario, storytelling output, presenter script`
Push to master.
Run: `openclaw system event --text "Done: VP demo — curated scenario with dramatic storytelling" --mode now`
