# Skill Loader

Production-grade skill loading system supporting multiple sources with validation and error handling.

## Features

- **YAML Loading**: Single skills or skill packs
- **Python Module Loading**: Import skills from .py files or modules
- **SkillStore Loading**: Load from database-backed store
- **Directory Loading**: Batch load all skills from a directory
- **Validation**: Comprehensive schema validation with detailed error reporting
- **Field Normalization**: Handles legacy YAML formats automatically
- **Error Handling**: Graceful degradation with detailed error messages

## Quick Start

```python
from core.skills.loader import SkillLoader

loader = SkillLoader()

# Load from YAML
skills = loader.load_from_yaml("skills/my_skill.yaml")

# Load a skill pack
skills = loader.load_pack("skills/customer_support_pack.yaml")

# Load with validation
skills, errors = loader.validate_and_load("skills/my_skill.yaml")
if errors:
    print("Validation errors:", errors)
```

## API

### `load_from_yaml(path: str) -> list[Skill]`

Load skills from a YAML file. Supports both single skill files and skill packs.

**YAML Format (Single Skill):**
```yaml
id: skill-001
name: keyword_expansion
kind: build
version: "1.0"
description: Expand routing keywords
capabilities:
  - keyword_expansion
mutations:
  - name: expand_keywords
    description: Add keywords
    target_surface: routing
    operator_type: append
triggers:
  - failure_family: routing_error
tags: [routing, keywords]
```

**YAML Format (Skill Pack):**
```yaml
skills:
  - id: skill-001
    name: keyword_expansion
    ...
  - id: skill-002
    name: instruction_hardening
    ...
```

**Raises:** `SkillLoadError` if file not found, invalid YAML, or parsing fails

---

### `load_pack(pack_path: str) -> list[Skill]`

Load a skill pack (YAML file with multiple skills). Alias for `load_from_yaml` that explicitly expects a pack format.

---

### `load_from_python(module_path: str) -> list[Skill]`

Load skills from a Python module. The module can define skills in three ways:

**Method 1: SKILLS constant**
```python
from core.skills.types import Skill, SkillKind

SKILLS = [
    Skill(
        id="custom-001",
        name="custom_skill",
        kind=SkillKind.BUILD,
        version="1.0.0",
        description="A custom skill",
    ),
]
```

**Method 2: get_skills() function**
```python
def get_skills():
    return [
        Skill(...),
        Skill(...),
    ]
```

**Method 3: Module-level Skill instances**
```python
skill1 = Skill(...)
skill2 = Skill(...)
```

**Args:**
- `module_path`: Python module path (e.g., `"plugins.my_skills"`) or file path (e.g., `"/path/to/module.py"`)

---

### `load_from_store(skill_ids: list[str], store: SkillStore) -> list[Skill]`

Load skills from a SkillStore by IDs.

**Example:**
```python
from core.skills.store import SkillStore

store = SkillStore("skills.db")
skills = loader.load_from_store(["skill-001", "skill-002"], store)
```

**Returns:** List of found skills (may be fewer than requested if some IDs don't exist)

---

### `validate_and_load(path: str) -> tuple[list[Skill], list[str]]`

Load skills from a file with validation. Does not raise exceptions on validation errors.

**Returns:** `(loaded_skills, error_messages)`

**Example:**
```python
skills, errors = loader.validate_and_load("skills/my_skill.yaml")
if errors:
    for error in errors:
        print(f"Validation error: {error}")
else:
    print(f"Loaded {len(skills)} valid skills")
```

---

### `load_directory(directory: str, recursive: bool = False, validate: bool = True) -> tuple[list[Skill], list[str]]`

Load all skill files from a directory.

**Args:**
- `directory`: Path to directory containing skill files
- `recursive`: Whether to search subdirectories
- `validate`: Whether to validate skills before returning

**Returns:** `(loaded_skills, error_messages)`

**Example:**
```python
skills, errors = loader.load_directory("skills/", recursive=True)
print(f"Loaded {len(skills)} skills with {len(errors)} errors")
```

## Field Normalization

The loader automatically normalizes YAML field names to handle legacy formats:

- `mutation_type` → `operator_type` (in mutations)
- `surface` → `description` (in examples)
- Missing `id` → Generated from `name`
- Version `"1"` → `"1.0.0"` (semver normalization)

## Error Handling

All loading methods raise `SkillLoadError` for irrecoverable errors:
- File not found
- Invalid YAML/Python syntax
- Missing required fields
- Parsing failures

For validation errors, use `validate_and_load()` which returns errors instead of raising.

## Testing

Run the comprehensive test suite:

```bash
python -m pytest tests/test_skills_loader.py -v
```

Test coverage:
- YAML loading (single and packs)
- Python module loading (all 3 methods)
- SkillStore loading
- Validation
- Directory loading (recursive and non-recursive)
- Error handling and edge cases

## Example

See `examples/skill_loader_demo.py` for a complete demonstration:

```bash
PYTHONPATH=. python examples/skill_loader_demo.py
```

## Production Notes

- **Logging**: Uses Python's standard logging. Set log level to control verbosity.
- **Thread Safety**: SkillLoader is thread-safe when used with thread-safe SkillStore.
- **Performance**: Directory loading with `validate=False` is significantly faster for large skill sets.
- **Validation**: The validator checks against strict schema rules. Some legacy YAML files may have warnings for custom operator_types or target_surfaces.
