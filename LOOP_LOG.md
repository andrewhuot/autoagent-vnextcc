# Vision-loop iteration cursor

Entries are oldest → newest. One line per action.

- iter-0 bootstrap: servers up on :5173/:8000, live mode confirmed (mock_mode=false), Gemini key recognized, Playwright chromium installed, drive.py harness in place, persistent Chromium attached.
- iter-1 snap /build: main content pane is EMPTY (#B1 blocker). Investigating Build.tsx.
- iter-2 /build: #B1 was race, harness mitigation applied. Typed FAQ Buddy prompt, clicked Generate. Draft panel shows financial-services template instead of customer-support (#B3 blocker). Investigated transcript_intelligence; traced to LLM 403 (#E1) + domain-detection if-chain that lets later matches override earlier.
- iter-3 /build: confirmed sandbox egress blocks Gemini API entirely (403 on any request, with/without key, even bare root). Environment limitation, not code. Pivoting: fix UX gaps that affect BOTH live and fallback modes.
- iter-4 fixes: #B3 domain detection rewritten as scored matcher with priority order; verified 9/9 prompts. #B4 JourneyActionPanel always-stack CSS; verified desc_width 0→424px. Committed (25ce505).
- iter-5 /build re-walk: FAQ Buddy draft now shows customer-service template (tools: lookup_customer, get_ticket_history; evals: first_contact_resolution). Saved as agent-v001. Build → Eval handoff URL correct: /evals?agent=agent-v001&new=1.
- iter-6 /workbench: #W1 (blocker) Workbench ignores ?agent= param; always loads hardcoded Airline Support default. #W2 (a11y) two h1s → fixed by demoting project-name h1 to h2. #W3 (polish) missing document.title.
- iter-7 /evals: works well. Agent selector carries FAQ Buddy. Eval run completes. "Optimize candidate" link carries agent= + evalRunId=.
- iter-8 /optimize: #O1 casing mismatch fixed. #O2 click doesn't surface failure under #E1.
- iter-9 /improvements, /deploy: clean empty states, good handoff copy, single h1, titles set. FAQ Buddy v1 · Candidate appears in Deploy version selector — config propagation works end-to-end.
- iter-10 final sweep: summary table in TESTING_NOTES, commit + push.
