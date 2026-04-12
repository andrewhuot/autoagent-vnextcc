# Workbench Deep Dive Plan - Codex

## Mission

Write a product-clear Workbench feature deep dive, wire it into docs navigation, and finish with validation, commit, push, and completion signal.

## Reader

Smart operator, PM, or engineer using AgentLab for real agent improvement work. The doc should explain what Workbench does, where it fits, and where its responsibilities stop without implying unavailable magic.

## Plan

1. Read required product docs and current Workbench surfaces.
2. Cross-check Workbench behavior against existing product language and the harness audit.
3. Draft `docs/features/workbench.md` around the real workflow: intent, use cases, readiness, restart/history behavior, Eval handoff, and limits.
4. Add discoverability links in the most relevant existing docs.
5. Re-read from a first-time operator perspective, verify paths/links, and self-review for overclaiming.
6. Commit, push, and send the required `openclaw` completion event.

## Working Findings

- Branch confirmed: `docs/workbench-deep-dive-codex`.
- Initial worktree was clean before this note was created.
- Existing repo-level `findings.md` contains prior campaign notes and should not be rewritten for this pass.
- The requested relative path `docs/plans/2026-04-12-cohesive-product-hardening.md` is not present in this worktree. The same plan exists at `/Users/andrew/Desktop/agentlab/docs/plans/2026-04-12-cohesive-product-hardening.md` and was read from there.
- Existing docs describe the main loop as `BUILD -> EVAL -> COMPARE -> OPTIMIZE -> REVIEW -> DEPLOY`, but newer navigation and hardening notes insert Workbench between Build and Eval for the guided operator journey.
- Current navigation metadata includes `/workbench` under Build with title `Agent Builder Workbench`.
- Workbench is a streaming, two-pane agent-building harness: conversation and plan tree on the left, active artifact/workspace on the right.
- The Eval bridge endpoint materializes the generated Workbench config into the real AgentLab workspace and returns Eval/Optimize request shapes. It explicitly does not start Eval, start Optimize, or call AutoFix.
- Bridge readiness states visible in code include `draft_only`, `needs_materialization`, `ready_for_eval`, `awaiting_eval_run`, and `ready_for_optimize`, plus blocked states with reasons.
- Restart behavior should be described conservatively: the UI hydrates persisted project/run/turn state and marks stale in-flight runs as interrupted historical snapshots; it is not true checkpoint-based resume.
- The harness audit warns that Workbench is useful and durable, but docs must not imply magic: autonomous iteration, completion evidence, live/mock provenance, and optimizer handoff should be described within their implemented limits.

## Validation Log

- Drafted `docs/features/workbench.md` with workflow, surface comparison, readiness states, restart/history behavior, limitations, practical example, API endpoints, and troubleshooting.
- Updated discoverability links and navigation language in `README.md`, `docs/app-guide.md`, `docs/platform-overview.md`, `docs/UI_QUICKSTART_GUIDE.md`, and `docs/features/context-workbench.md`.
- Ran `git diff --check`: passed.
- Ran a relative Markdown link/path validator over changed docs and the new working note: all checked relative links resolve.
- Ran fresh-reader testing with a subagent, then tightened first-time-operator context around location, core terms, bridge decision points, Eval setup, blockers, and review-gate meaning.
- Ran second-pass fresh-reader check: no blocking ambiguity or overclaiming issues found.
- Pending: final diff check, commit, push.
