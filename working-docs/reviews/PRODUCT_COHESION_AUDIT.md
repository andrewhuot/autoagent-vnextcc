# Product Cohesion Audit: AutoAgent CLI + UI

## Executive Summary

AutoAgent has a real product core: the build → eval → optimize → review → deploy loop is understandable, mock mode makes first-run exploration practical, and the UI navigation now broadly follows the same workflow as the CLI. The biggest cohesion risk is not missing capability, but drift: command names, page names, startup instructions, and transition language have diverged enough that a new user can tell the system is one product conceptually while still feeling like they are learning two different interfaces.

The highest-priority work is to enforce one shared taxonomy across CLI, UI, and docs, and to make the mock-to-live transition an explicit phase change instead of an ambient concept sprinkled through multiple surfaces. Once those are tightened, the rest of the product will feel substantially more intentional.

## Strengths

- The core loop is strong. A user can understand the main operating model as: create or refine a config, run evals, optimize, review the proposed change, then deploy.
- Mock mode is the right default for onboarding. It lets a new user experience the product without credentials or spend anxiety.
- The UI sidebar architecture is mostly sensible. Home, Build, Eval, Optimize, Review, Deploy, Observe, and Govern are understandable buckets.
- The CLI selector pattern (`latest`, `pending`, `active`) is a useful abstraction that lowers cognitive load once users learn it.
- The Build surface is directionally cohesive. Prompt, transcript, builder chat, and saved artifacts belong together.
- The Setup page is a good idea. It gives the product a readiness checkpoint instead of dropping users directly into generation or optimization.

## Cohesion Gaps

1. **Severity: P0**
   **Description:** AutoAgent does not yet enforce a single canonical taxonomy across CLI, UI, and docs. Examples include `server` vs `serve`, `judges` vs **Judge Ops**, `skill` vs **Skills**, `logs` vs **Conversations**, and `trace blame` vs **Blame Map**. This creates the feeling that the UI uses product language while the CLI uses implementation language.
   **Recommended fix:** Define one shared command-and-surface taxonomy as the source of truth, then drive CLI help copy, sidebar labels, quickstart docs, and route metadata from it. Where legacy names are important, implement explicit aliases instead of letting docs invent them.

2. **Severity: P0**
   **Description:** The mock-to-live transition is conceptually central but operationally under-structured. Users are introduced to live mode early, yet most of the first-run flow is happiest in mock mode. Before this audit, provider setup also accepted ambiguous `provider:model` input that could poison live execution state.
   **Recommended fix:** Make mock mode the official onboarding phase in both CLI and UI. Move live setup into a clearly labeled second phase with validation, a success checkpoint, and language that distinguishes “exploring the product” from “using real provider calls.”

3. **Severity: P1**
   **Description:** The UI default landing page and the onboarding story do not match. The app root redirects to **Build**, while the actual first-run guidance should begin with **Setup** and then **Dashboard**.
   **Recommended fix:** Add a first-run gate or banner that points new users to **Setup** before they enter the generation loop. If the workspace is uninitialized or unhealthy, the product should say so immediately.

4. **Severity: P1**
   **Description:** The optimize → review → deploy transition is not consistently expressed. The CLI quickstart used to skip review in the daily flow, `compare candidates` is often empty immediately after optimize, and `ship` collapses multiple concepts into one shortcut.
   **Recommended fix:** Standardize one canonical flow everywhere: optimize, inspect reviewable change, apply review, then deploy. Treat `ship` as an expert shortcut and `compare candidates` as optional analysis, not the main path.

5. **Severity: P1**
   **Description:** Deploy semantics are blurred. The product uses strong production language like canary, immediate, ship, and release, but the primary deploy flow is still largely a local rollout/version-state surface. External deployment targets such as CX are separate, but that distinction is not obvious.
   **Recommended fix:** Split the concept explicitly into two layers: `Local rollout state` and `External deployment target`. The UI and CLI should both explain which layer the current action affects.

6. **Severity: P1**
   **Description:** Setup is valuable but overloaded. Workspace health, mode readiness, database state, MCP client installation, and CLI shortcut guidance all appear at once without a clear staged hierarchy.
   **Recommended fix:** Turn Setup into a checklist with ordered sections: workspace, providers, stores, integrations, then next actions. Preserve the information, but stage it.

7. **Severity: P1**
   **Description:** The permission model exists, but it is not yet a first-class cross-surface concept. There is a CLI command group, a settings file, and prompt-based enforcement, but no obvious UI home and no single explanation users are likely to discover organically.
   **Recommended fix:** Add a canonical permissions surface to the UI and point both guides to `autoagent permissions show` / `set`. Also decide whether `bypass` is truly user-facing or internal automation vocabulary.

8. **Severity: P2**
   **Description:** Build terminology still carries legacy drift. The product contains references to Build, Builder, Agent Studio, Assistant, Prompt Studio, Transcript Studio, Prompt, and Transcript across routes, docs, and page content.
   **Recommended fix:** Keep the route redirects for backward compatibility, but consolidate user-facing language to one vocabulary and document legacy terms only as redirects.

9. **Severity: P2**
   **Description:** Setup, Dashboard, and CLI Status overlap in purpose, but their roles are not sharply explained. New users can reasonably ask: when do I use Setup vs Dashboard vs `autoagent status`?
   **Recommended fix:** Codify the mental model: Setup = readiness, Dashboard = health and recent performance, Status = compact CLI snapshot. Repeat that framing in docs and page descriptions.

10. **Severity: P2**
    **Description:** Some UI pages are aggregation surfaces with no true 1:1 CLI equivalent, but the docs previously implied exact parity. Event Log is the clearest example.
    **Recommended fix:** Stop forcing false command equivalences. In docs, label these as “closest CLI surface” or mark them explicitly as UI-native views.

11. **Severity: P2**
    **Description:** Shell free-text routing is a promising bridge between product language and command language, but users still do not get much visibility into what is safe, what is read-only, and what could mutate state.
    **Recommended fix:** Add clearer previews in the shell before executing routed actions, and tag actions as read-only vs mutating where practical.

## Information Architecture Issues

- The app root goes to **Build**, while the first-run success path should start in **Setup**.
- **Review** exists both as a top-level sidebar section and as a tab embedded inside **Optimize**, which is logically understandable but visually redundant.
- **Observe** and **Govern** include strong first-class pages plus several advanced surfaces that are outside the first-run path. Without progressive disclosure, this makes the product feel wider than it feels deep.
- **Deploy** is positioned as a primary stage in the journey, but the distinction between local rollout bookkeeping and external deployment remains hidden.
- The UI currently has a stronger concept of page grouping than the CLI has of command-group naming consistency.

## Naming/Terminology Inconsistencies

- `autoagent server` vs the previously documented `autoagent serve`
- **Judge Ops** page vs `autoagent judges`
- **Skills** page vs `autoagent skill`
- **Conversations** page vs `autoagent logs`
- **Blame Map** page vs `autoagent trace blame`
- **Prompt** / **Transcript** tabs vs older “Prompt Studio” / “Transcript Studio” language
- **Build** as the primary page vs legacy **Builder**, **Agent Studio**, and **Assistant** route names
- **Memory** in the nav vs **Project Memory** in page/component naming
- **Ship**, **Deploy**, and **Release** as related but not clearly tiered verbs

## Dead Ends and Missing Transitions

- `autoagent compare candidates` often produces no useful output immediately after a normal optimize run, so it does not work as a dependable “next step” in onboarding.
- The Build UI produces a config successfully, but the old docs described a nonexistent **Save & Continue** action instead of the real next actions in the YAML panel.
- The UI root opens **Build** without a strong nudge toward **Setup**, which creates an avoidable first-run branch.
- Event Log is informative, but it does not naturally point users toward the next corrective action.
- Deploy explains state after the fact, but not clearly enough before the user chooses between canary and immediate.

## Recommendations

1. Build and enforce a shared taxonomy layer for commands, page names, route metadata, and docs labels.
2. Make mock mode the explicit onboarding phase and live mode the explicit second phase.
3. Add first-run routing or a Setup-first banner in the UI when readiness checks are incomplete.
4. Standardize the primary journey everywhere as build → eval → optimize → review → deploy.
5. Reframe deploy language into local rollout state vs external deployment target.
6. Turn Setup into an ordered checklist instead of a flat dashboard of readiness facts.
7. Give permissions a visible canonical surface and document it once.
8. Add doc linting for dead links, stale command names, and route/label drift.
