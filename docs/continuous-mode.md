# Continuous Mode

## Overview

Continuous mode turns the ad-hoc `ingest -> score -> analyze -> propose`
workflow into a background loop that wakes up on a schedule, picks up
any new production traces, runs them through your eval suite, checks
for score regressions or distribution drift, and queues an improvement
attempt when something looks off. It never auto-deploys — every
proposal still lands in the improvement queue for human review.

Use it when you have a live agent emitting traces and you want
regression / drift alerts without manually re-running `agentlab eval
ingest` each day. If you are still iterating on the eval suite itself,
stick with the one-shot flow; continuous mode only pays off once the
suite is stable enough that a score drop means something.

## Prerequisites

- A workspace with an eval suite you trust. `agentlab eval run` should
  exit cleanly on the baseline before you wire up continuous mode.
- Provider API keys exported in the environment (`ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, etc.) or loaded via your daemon's environment file.
  Continuous mode respects `AGENTLAB_STRICT_LIVE=1` and will refuse to
  fall back to mock adapters.
- A trace source. This is a directory of JSONL files; the loop discovers
  files whose mtime is greater than the per-workspace watermark.

## One-shot cycle

Run a single cycle manually to smoke-test the wiring:

```
agentlab loop run --schedule continuous --trace-source ~/traces
```

Each cycle does, in order:

1. **Ingest** — discover trace files under `--trace-source` with mtime
   greater than the watermark, convert them to eval cases, and append
   them to the workspace's case store.
2. **Score** — run the eval suite against the new cases, record the
   run in the lineage store.
3. **Regression check** — compare the new median score against the
   median-of-last-N baseline (default N=5, threshold 0.05). If the
   median drops by at least the threshold, mark the cycle regressed.
4. **Drift check** — compute KL divergence between the new score
   distribution and the rolling baseline (see below).
5. **Queue attempt** — if regressed or drifted, call
   `run_improve_run_in_process(mode="analyze_and_propose")` and record
   the attempt id. The attempt sits in the improvement queue; no
   deploy happens.

The watermark advances per-file as each trace is processed, so a crash
mid-cycle does not cause re-ingestion on the next run.

## Scheduling

For unattended operation, wrap the command in a system daemon. Two
reference samples ship with the repo — **copy and edit them before
installing**; they are not auto-installed.

- **systemd** (Linux user scope):
  [`contrib/systemd/agentlab-loop.service`](../contrib/systemd/agentlab-loop.service).
  Copy to `~/.config/systemd/user/`, edit `WorkingDirectory` and
  `ExecStart`, then `systemctl --user daemon-reload && systemctl --user
  enable --now agentlab-loop.service`.

- **launchd** (macOS user agent):
  [`contrib/launchd/com.agentlab.loop.plist`](../contrib/launchd/com.agentlab.loop.plist).
  Copy to `~/Library/LaunchAgents/`, edit the `ProgramArguments` paths
  and the `StandardOutPath` / `StandardErrorPath`, then `launchctl load
  ~/Library/LaunchAgents/com.agentlab.loop.plist`.

The daemon does not make deploy decisions. It ingests, scores, detects,
and queues. A human still reviews every proposed improvement via
`agentlab improve list` or the Workbench `/improve` commands before
anything reaches production.

## Notifications

Wire the continuous loop to a webhook or Slack channel so regressions
and drift surface outside the terminal. Channels are registered via
the workspace notifications config; see the CLI reference for
`agentlab notifications add`.

Event types emitted:

- `regression_detected` — median score dropped past the regression
  threshold against the rolling baseline.
- `improvement_queued` — an attempt was queued in response to a
  regression or drift event. Payload includes the attempt id.
- `continuous_cycle_failed` — the cycle itself raised (ingest error,
  eval run crash, lineage store write failure, etc.). Always emitted;
  never deduped.
- `drift_detected` — KL divergence between the current production
  score distribution and the baseline exceeds `drift_threshold`.

Notifications are deduped by `(event_type, workspace, signature)` in a
SQLite-backed store at `<workspace>/.agentlab/notification_log.db` with
a **1-hour window** (`DEFAULT_DEDUPE_WINDOW_SECONDS = 3600`). The same
regression signature within an hour fans out once. `continuous_cycle_failed`
is intentionally excluded from dedupe so repeated failures always alert.

## Drift detection

Continuous mode computes KL divergence between the production score
distribution and a rolling baseline on each cycle. Defaults:

- `drift_threshold` = 0.2 (emit `drift_detected` when KL exceeds this)
- `min_baseline_size` = 20 (skip drift check until the baseline has at
  least 20 runs; avoids spurious alerts during warmup)

When drift fires, the event payload includes a recommendation to
re-ingest recent traces so the eval suite sees the new distribution:

```
agentlab eval ingest --from-traces <path> --since 7d
```

This is a signal that the production distribution has shifted in a way
your eval suite is under-sampling — you probably want to extend the
suite rather than just chase the score.

## Cost-aware tradeoffs

Optimizer attempts are ranked on a Pareto frontier over quality,
safety, and cost. To see the top N non-dominated candidates:

```
agentlab optimize --show-tradeoffs 5
```

This prints a table of up to 5 non-dominated candidates with their
quality, safety, and cost scores. Cost weight is opt-in: by default the
weight is 0.0 so cost is a tiebreaker rather than a driver. Set a
non-zero cost weight in your workspace config to have the optimizer
actively prefer cheaper candidates.

## Strict-live

Continuous mode respects `AGENTLAB_STRICT_LIVE=1` / `permissions.strict_live:
true` in `.agentlab/settings.json`. If strict-live is enabled and no
provider API key is detected, the loop refuses to silently fall back to
a mock adapter and exits with code **12** (`EXIT_MOCK_FALLBACK`). Fix
by exporting the provider key (or setting it via your daemon's
`EnvironmentFile` / `EnvironmentVariables`) and re-running.

## Troubleshooting

- **Watermark**: per-workspace at
  `<workspace>/.agentlab/continuous_watermark.json`. Delete it to force
  a full re-ingest of all trace files on the next cycle:

  ```
  rm <workspace>/.agentlab/continuous_watermark.json
  ```

- **Dedupe DB**: per-workspace at
  `<workspace>/.agentlab/notification_log.db`. Delete to reset dedupe
  state (you'll get one immediate fan-out of any currently-suppressed
  alerts on the next cycle).

- **No new cycles**: check the daemon log (`journalctl --user -u
  agentlab-loop.service` for systemd,
  `~/Library/Logs/agentlab-loop.err` for launchd). If the loop exited
  12, you hit strict-live with no provider key.

- **Drift alert won't clear**: the dedupe window is 1 hour; after that,
  the same drift signature can re-fire. If the drift is legitimate and
  you've extended the suite, the score distribution should shift on
  the next cycle and the drift event will stop firing.

## Cross-references

- [Workbench Quickstart](workbench-quickstart.md) — interactive TUI for
  inspecting continuous-mode artifacts: eval case grid, failure cards,
  `/attempt-diff`, `/lineage`, `/improve accept --edit`.
- [Conversational Workbench](r7-workbench-as-agent.md) — natural-language
  entrypoint to the same command surface.
- [Tool Permission Reference](r7-tool-permission-reference.md) — for
  strict-live and permission configuration.
