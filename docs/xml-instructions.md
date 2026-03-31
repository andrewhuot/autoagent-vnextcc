# XML Instructions

AutoAgent now defaults to XML-based agent instructions for new workspaces and starter templates.

This follows Google Cloud CX Agent Studio guidance for structuring instructions so models can separate role, goals, constraints, taskflow, and examples more reliably.

Reference:

- Google Cloud CX Agent Studio instructions guide: `https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/instruction`

## Why XML

Plain-text instructions still work, but XML has a few practical advantages:

- It makes the agent's role and objective explicit.
- It separates hard constraints from softer persona guidance.
- It gives taskflow steps a stable structure that can be parsed, validated, and merged.
- It makes eval variants easier because you can override specific sections instead of rewriting the whole prompt.
- It gives the Build UI and CLI a shared format to edit safely.

## Supported XML Structure

AutoAgent follows the Google-recommended XML tags:

- `<role>`: the agent's core responsibility
- `<persona>`: tone and behavior guidance
- `<primary_goal>`: nested inside `<persona>`
- `<constraints>`: hard rules and limitations
- `<taskflow>`: the high-level flow of the conversation
- `<subtask>`: a named flow segment within `<taskflow>`
- `<step>`: a named action unit inside a subtask
- `<trigger>`: the condition that activates a step
- `<action>`: what the agent should do when the trigger matches
- `<examples>`: inline few-shot examples

AutoAgent also preserves free text before the first XML tag as preamble/context when present.

## Example

```xml
CURRENT CUSTOMER: {username}

<role>Customer support router.</role>
<persona>
  <primary_goal>Route customer requests to the right specialist and keep the interaction safe.</primary_goal>
  Be calm, concise, and easy to follow.
  Ask one clarifying question when a required detail is missing.
</persona>
<constraints>
  1. Protect customer privacy and never expose another customer's data.
  2. Refuse unsafe or policy-violating requests politely.
</constraints>
<taskflow>
  <subtask name="Support Routing">
    <step name="Identify Intent">
      <trigger>A customer asks for help.</trigger>
      <action>Determine whether the request belongs to support, orders, or recommendations.</action>
    </step>
    <step name="Clarify Missing Details">
      <trigger>The request is ambiguous or lacks a required detail.</trigger>
      <action>Ask one focused clarifying question before routing or answering.</action>
    </step>
  </subtask>
</taskflow>
<examples>
  EXAMPLE 1:
  Begin example
  [user]
  Where is my order #1001?
  [model]
  I can help with that. I'll route this to the order specialist so we can check the latest shipping status.
  End example
</examples>
```

## Where AutoAgent Uses XML

AutoAgent now uses XML instructions in four main places:

1. Starter templates in `docs/templates/`
2. The default base config in `agent/config/base_config.yaml`
3. The eval adapter in `agent/eval_agent.py`
4. The Build page XML instruction studio in `web/src/pages/Build.tsx`

For workspace configs, the root instruction usually lives in `prompts.root`.

## Backward Compatibility

AutoAgent still supports plain-text instructions.

Compatibility behavior:

- Existing plain-text configs continue to load.
- `autoagent instruction validate` will tell you when a prompt is still plain text.
- `autoagent instruction migrate` converts a plain-text instruction into the XML default.
- The eval adapter can handle mixed inputs, including XML root instructions plus plain-text specialist instructions.

## CLI Workflows

The new `instruction` command group operates on the active workspace config by default.

### Show the current instruction

```bash
autoagent instruction show
```

### Validate the XML structure

```bash
autoagent instruction validate
```

### Edit the instruction in your editor

```bash
autoagent instruction edit
```

### Generate a fresh XML draft from a brief

```bash
autoagent instruction generate --brief "customer support agent for order tracking and refunds"
```

Apply the generated draft back to the active config:

```bash
autoagent instruction generate --brief "customer support agent for order tracking and refunds" --apply
```

### Migrate plain text to XML

```bash
autoagent instruction migrate
```

## Eval Overrides

The eval adapter now accepts XML section overrides per run.

Programmatically, this is passed inside the config payload as `_instruction_overrides`.

From the CLI, you can provide a YAML or JSON file:

```yaml
constraints:
  - Always confirm the cancellation reason before taking action.
```

Run an eval with that override:

```bash
autoagent eval run --instruction-overrides instruction_override.yaml
```

This is useful when you want to compare variants of:

- constraint wording
- persona guidance
- examples
- taskflow changes

without editing the baseline config itself.

## Build UI

The Build page now includes an XML Instruction Studio with:

- raw XML editing
- form-based section editing
- inline validation feedback
- a syntax-highlight preview
- guide-inspired example snippets

The prompt-mode builder includes the validated XML draft when you generate an agent, so instruction authoring is part of the build flow instead of a separate cleanup step.

## Migration Heuristics

`agent/migrate_to_xml.py` uses a lightweight heuristic migration flow:

- infer the role from phrases like "You are ..."
- extract likely hard constraints from "always", "never", "must", "verify", and similar phrases
- infer a primary goal from the user's help/assist/route language
- build a default taskflow based on the domain
- seed a small example block

This is intentionally conservative. It gives you a clean starting point, not a perfect final prompt.

After migration, you should still review:

- whether the role is worded correctly
- whether the constraints are truly hard rules
- whether the taskflow reflects your real routing logic
- whether examples are necessary or should be removed

## Template Guidance

Bundled starter templates now include XML root instructions with examples.

When creating your own templates, aim for:

- one clear role
- one primary goal
- short constraints that behave like policy
- taskflow steps that are easy to test in evals
- examples only when they solve a real behavior gap

## Notes on Examples

Google's guidance recommends using examples sparingly.

In practice:

- Start with instructions first.
- Add examples only when the model still misbehaves after instruction cleanup.
- Prefer one or two focused examples over a long example catalog.
- Keep examples descriptive, not exhaustive.

## Implementation Notes

Backend modules added for this feature:

- `agent/instruction_builder.py`
- `agent/migrate_to_xml.py`

The shared builder supports:

- `parse_xml_instruction(xml_text)`
- `build_xml_instruction(sections)`
- `validate_xml_instruction(xml_text)`
- `merge_xml_sections(base, override)`

## Recommended Workflow

For a new workspace:

1. Run `autoagent new my-agent --template customer-support`
2. Inspect the default XML with `autoagent instruction show`
3. Adjust it with `autoagent instruction edit` or the Build UI
4. Validate it with `autoagent instruction validate`
5. Run `autoagent eval run`
6. Use `--instruction-overrides` when you want to compare XML variants quickly
