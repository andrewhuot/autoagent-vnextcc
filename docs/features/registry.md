# Modular Registry

Version-controlled storage for skills, policies, tool contracts, and handoff schemas. The registry is the single source of truth for reusable agent components.

## Registry types

| Type | Description | Example |
|------|-------------|---------|
| `skills` | Agent capabilities and behaviors | "order_lookup", "product_recommendation" |
| `policies` | Decision-making rules and guardrails | "refund_policy", "escalation_rules" |
| `tool_contracts` | Tool input/output schemas and descriptions | "search_api", "payment_gateway" |
| `handoff_schemas` | Inter-agent handoff protocols | "support_to_orders", "orders_to_billing" |

## Versioning

Every registry item is automatically versioned on write. You can:

- View any historical version
- Diff between versions
- Roll back to a previous version

Versions are immutable. Updates create new versions, never overwrite.

## CRUD operations

### Create

```bash
# Add a skill from a YAML file
autoagent registry add skills order_lookup --file skills/order_lookup.yaml

# Add a policy
autoagent registry add policies refund_policy --file policies/refund.yaml
```

### Read

```bash
# List all skills
autoagent registry list --type skills

# Show a specific item (latest version)
autoagent registry show skills order_lookup

# Show a specific version
autoagent registry show skills order_lookup --version 2
```

### Diff

```bash
# Compare two versions
autoagent registry diff skills order_lookup 1 2
```

## Import / Export

Bulk import from a YAML or JSON file:

```bash
autoagent registry import registry_export.yaml
```

The import file should contain items organized by type:

```yaml
skills:
  order_lookup:
    description: "Look up order details by order ID"
    parameters:
      order_id: { type: string, required: true }
  product_search:
    description: "Search product catalog"
    parameters:
      query: { type: string, required: true }

policies:
  refund_policy:
    conditions: ["order_age < 30d", "item_condition == unused"]
    action: "approve_refund"
```

## Validation

Handoff schemas are validated on creation to ensure they define:

- Source and target agent paths
- Required context fields
- Optional context fields with defaults

Invalid schemas are rejected with a descriptive error.

## Search

Search across all registry types or filter by type:

```bash
# Via CLI
autoagent registry list --type skills
```

```bash
# Via API
curl "http://localhost:8000/api/registry/search?q=order&type=skills"
```

## CLI commands

```bash
autoagent registry list [--type TYPE] [--db PATH]
autoagent registry show <type> <name> [--version N] [--db PATH]
autoagent registry add <type> <name> --file <path> [--db PATH]
autoagent registry diff <type> <name> <v1> <v2> [--db PATH]
autoagent registry import <path> [--db PATH]
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/registry/search` | Search items by query |
| `POST` | `/api/registry/import` | Bulk import from file |
| `GET` | `/api/registry/{type}` | List items of a type |
| `GET` | `/api/registry/{type}/{name}/diff` | Diff versions |
| `GET` | `/api/registry/{type}/{name}` | Get a specific item |
| `POST` | `/api/registry/{type}` | Create a new item |

## Integration with optimization

The optimizer can propose mutations that reference registry items. For example, a `skill` mutation might add a new skill from the registry to the agent config. Registry items that are pinned via human control are excluded from optimizer modifications.
