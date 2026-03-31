# XML Instructions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make XML instructions the default authoring format for AutoAgent agents while preserving backward compatibility with existing plain-text instructions.

**Architecture:** Add a shared `agent.instruction_builder` module that detects, parses, validates, merges, and serializes Google-style XML instructions. Reuse that module from eval and CLI flows, convert bundled starter templates to XML, and add a Build UI editor that offers both raw XML and section-based editing on top of the same validation model.

**Tech Stack:** Python, Click, FastAPI-adjacent route types, React, TypeScript, Vitest/Jest-style frontend tests, Pytest.

---

### Task 1: Lock the XML schema in tests

**Files:**
- Create: `tests/test_instruction_builder.py`
- Modify: `tests/test_eval_agent.py`
- Modify: `tests/test_cli_commands.py`

**Step 1: Write the failing parser and validator tests**

Cover:
- Parsing valid XML into structured sections.
- Building XML from structured sections.
- Rejecting malformed XML.
- Rejecting XML missing required structural sections.
- Merging section overrides.

**Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_instruction_builder.py tests/test_eval_agent.py tests/test_cli_commands.py -q`

**Step 3: Add failing eval and CLI contract tests**

Cover:
- Eval agent accepting XML root instructions and applying rule overrides.
- `autoagent instruction show|validate|migrate|generate` command behavior.

**Step 4: Run the targeted tests again**

Expected: failures due to missing XML implementation and CLI commands.

### Task 2: Implement shared XML instruction support

**Files:**
- Create: `agent/instruction_builder.py`
- Create: `agent/migrate_to_xml.py`
- Modify: `agent/__init__.py` if export convenience is useful

**Step 1: Write minimal implementation to satisfy parser tests**

Include:
- XML detection helper.
- `parse_xml_instruction(xml_text)`
- `build_xml_instruction(sections)`
- `validate_xml_instruction(xml_text)`
- `merge_xml_sections(base, override)`
- Plain-text migration heuristics for `migrate_to_xml.py`

**Step 2: Run backend tests**

Run: `pytest tests/test_instruction_builder.py -q`

**Step 3: Refactor for clarity without expanding scope**

Keep XML schema constrained to documented tags and maintain readable data structures.

### Task 3: Integrate eval and CLI

**Files:**
- Modify: `agent/eval_agent.py`
- Modify: `runner.py`
- Modify: `tests/test_eval_agent.py`
- Modify: `tests/test_cli_commands.py`

**Step 1: Add failing integration tests for overrides and validation**

Cover:
- XML instruction validation before live request execution.
- Override support for XML sections during eval runs.
- CLI command output and validation behavior.

**Step 2: Implement minimal eval and CLI support**

Add:
- XML-aware system prompt composition.
- New `instruction` command group.
- Editor integration using `$EDITOR` fallback for `instruction edit`.
- AI-assisted generation using bundled examples and migration heuristics.

**Step 3: Run targeted tests**

Run: `pytest tests/test_instruction_builder.py tests/test_eval_agent.py tests/test_cli_commands.py tests/test_runner.py -q`

### Task 4: Convert templates and defaults

**Files:**
- Modify: `docs/templates/customer-support.yaml`
- Modify: `docs/templates/healthcare-intake.yaml`
- Modify: `docs/templates/it-helpdesk.yaml`
- Modify: `agent/config/base_config.yaml`
- Modify: any other starter template files discovered during implementation

**Step 1: Write failing tests if template coverage is missing**

Add assertions that starter configs default to XML instructions and remain loadable.

**Step 2: Convert prompt strings to XML**

Ensure each template contains:
- Role and persona guidance.
- Constraints.
- Taskflow steps.
- Examples.

**Step 3: Run template and config-loading tests**

### Task 5: Add Build UI XML editor

**Files:**
- Modify: `web/src/pages/Build.tsx`
- Modify: `web/src/pages/Build.test.tsx`
- Modify: supporting `web/src/lib/types.ts` or helpers if needed

**Step 1: Add failing UI tests**

Cover:
- Raw XML view.
- Form view editing of key sections.
- Inline validation warnings.
- Guide example insertion.

**Step 2: Implement the editor**

Keep the feature practical:
- Toggle between raw XML and form mode.
- Syntax-friendly monospace editing.
- Inline validation.
- Example snippets from the Google guide.

**Step 3: Run frontend tests**

Run: `npm test -- --run Build.test.tsx` or the repo’s equivalent targeted command.

### Task 6: Update docs and verify end to end

**Files:**
- Create: `docs/xml-instructions.md`
- Modify: `docs/QUICKSTART_GUIDE.md`
- Modify: `docs/DETAILED_GUIDE.md`

**Step 1: Document the XML format thoroughly**

Include:
- Why XML is now default.
- Official section structure.
- Plain-text compatibility.
- CLI usage.
- Migration workflow.

**Step 2: Run final verification**

Run the smallest targeted backend and frontend test sets that prove the feature.

**Step 3: Review diff**

Run: `git diff --stat` and `git diff -- <key files>`

**Step 4: Notify completion**

Run:
```bash
openclaw system event --text "Done: XML agent instructions implemented — builder, templates, CLI, UI, docs" --mode now
```
