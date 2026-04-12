# UI Copy Cohesion Checklist

Scope: Item 5 product polish pass across navigation, labels, empty states, degraded states, and action wording.

Non-scope: backend truthfulness semantics, fake-progress remediation, data provenance changes, or Item 3 work.

## Shared Language Rules

- Status badges use shared product labels from `web/src/lib/utils.ts`.
- Raw API statuses can stay in data, but visible badges should use operator-facing labels.
- Empty and degraded states should answer three questions:
  - What state is this?
  - Why is it empty, blocked, waiting, or degraded?
  - What should the operator do next?
- Action labels should name the object of the action when ambiguity is possible.
- Historical surfaces should say when they are waiting for past events rather than implying live progress.

## Navigation And Shell

- [x] Simple guided flow separates `Optimize` and `Review` instead of collapsing both into `Improve`.
- [x] Guided flow order reads `Setup, Build, Eval, Optimize, Review, Deploy`.
- [x] The `/improvements` route is labeled as the Review step in guided navigation.
- [x] Existing route taxonomy remains intact; no new navigation surface was invented.

## Build

- [x] Saved Artifacts empty states show a `No data yet` state label.
- [x] Saved Artifacts explains that artifacts appear after generating, exporting, or saving a draft.
- [x] Saved Artifacts provides a next action for the operator.
- [x] Degraded artifact-loading states say the backend/API source is unavailable rather than implying an empty workspace.
- [x] Existing Build handoff copy stays normalized around saved drafts and Eval Runs.

## Agent Workbench

- [x] Completed candidates without a review gate use the canonical `Ready` label.
- [x] Blocked review gates use the canonical `Blocked` label.
- [x] Review-gate calls to action keep `Review required` language.
- [x] Interrupted/cancelled workbench states use `Interrupted` instead of a separate stopped label.
- [x] No Workbench backend state machine changes were made.

## Optimize

- [x] Pending optimizer reviews display `Review required` through the shared status language.
- [x] No-agent state is explicitly `Blocked`.
- [x] No-agent state tells the operator to open Build or select an existing agent.
- [x] No-history state is explicitly `No data`.
- [x] Optimize action wording keeps the selected saved config as the object of work.

## Improvements

- [x] History empty state uses `No data yet`.
- [x] History empty state explains decisions appear after accepted or rejected proposals.
- [x] History empty state points the operator back to pending reviews or Optimize.
- [x] Accepted/rejected history statuses use shared labels instead of raw underscored strings.
- [x] Review remains the label for approval decisions.

## Deploy

- [x] Missing deployment status uses `No data yet`.
- [x] Missing deployment status explains that status appears after a config has been deployed.
- [x] Missing canary state is labeled `Waiting`.
- [x] Missing canary state tells the operator to deploy a candidate with the canary strategy.
- [x] Canary promotion action is `Promote canary`, not a generic `Promote`.
- [x] Confirmation action is `Confirm canary promotion`, matching the object of the action.
- [x] Deployment history statuses use shared labels such as `Promoted`.
- [x] Deployment history empty state explains it is waiting for rollout events.

## Mock And Degraded Banners

- [x] Preview mode, frontend-only mode, rate-limit, and workspace-invalid banners already distinguish degraded/blocked causes.
- [x] Preview banner title and dismiss action use the same `Preview mode` language as the shared status helper.
- [x] Retry actions name the target: connection, provider retry, or workspace check.
- [x] Workspace invalid state remains globally visible even outside optimize routes.

## Validation Notes

- Targeted Vitest coverage added or updated for shared status language, shared empty-state language, sidebar navigation labels, Build saved-artifact empties, Workbench status labels, Optimize blocked state, Improvements history empty state, and Deploy canary/status copy.
- Playwright URL contract coverage passed against the Vite dev server on `http://127.0.0.1:5174`.
- Frontend production build passed after the targeted unit and route-contract checks.
- Repo-wide `npm run lint` still fails on existing React hook, fast-refresh, and explicit-`any` findings outside this Item 5 copy-polish scope.
- `tests/mock-mode-honesty.spec.ts` was attempted against the frontend-only Vite server and remained blocked by missing backend/mock health setup, so no Item 3 truthfulness behavior was changed in this pass.
