"""SQLite persistence for generated agent skills.

MIGRATION NOTE: This is now a backward-compatible wrapper around core/skills/store.
The old API surface is preserved for compatibility, but all data is stored in the
unified skill store format under the hood.
"""
from __future__ import annotations

from typing import Any

from core.skills.store import SkillStore as UnifiedSkillStore
from core.skills.types import (
    EffectivenessMetrics,
    Skill as UnifiedSkill,
    SkillKind,
    ToolDefinition,
)
from agent_skills.types import GeneratedFile, GeneratedSkill


class AgentSkillStore:
    """Backward-compatible wrapper around unified SkillStore.

    This maintains the old agent skills API while using the unified store underneath.
    All agent skills are converted to the RUNTIME kind in the unified format.
    """

    def __init__(self, db_path: str = ".agentlab/agent_skills.db") -> None:
        """Initialize the agent skill store.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self._unified_store = UnifiedSkillStore(db_path)
        # Keep a separate metadata store for gap data (not in unified schema)
        self._gap_store: dict[str, dict[str, Any]] = {}
        self._load_gaps()

    def _load_gaps(self) -> None:
        """Load gaps from metadata if they exist."""
        # Gaps are stored in skill metadata with a special prefix
        all_skills = self._unified_store.list(kind=SkillKind.RUNTIME)
        for skill in all_skills:
            if "gap_data" in skill.metadata:
                gap_id = skill.metadata.get("gap_id")
                if gap_id:
                    self._gap_store[gap_id] = skill.metadata["gap_data"]

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def _convert_to_unified(self, gen_skill: GeneratedSkill) -> UnifiedSkill:
        """Convert GeneratedSkill to unified Skill format."""
        # Build tools list if source_code exists
        tools = []
        if gen_skill.source_code:
            tools.append(
                ToolDefinition(
                    name=gen_skill.name,
                    description=gen_skill.description,
                    parameters={},  # Would need to parse from source_code
                    returns=None,
                    implementation=gen_skill.source_code,
                    sandbox_policy="read_only",
                )
            )

        # Convert instructions from config_yaml if exists
        instructions = gen_skill.config_yaml or ""

        # Build metadata to store all the extra fields
        metadata = {
            "gap_id": gen_skill.gap_id,
            "platform": gen_skill.platform,
            "skill_type": gen_skill.skill_type,
            "skill_name": gen_skill.name,  # Store the original name here
            "source_code": gen_skill.source_code,
            "config_yaml": gen_skill.config_yaml,
            "files": [f.to_dict() for f in gen_skill.files],
            "eval_criteria": gen_skill.eval_criteria,
            "estimated_improvement": gen_skill.estimated_improvement,
            "confidence": gen_skill.confidence,
            "review_notes": gen_skill.review_notes,
        }

        # Use skill_id as name to avoid collisions (agent skills can have same name but different IDs)
        # Store original name in metadata
        return UnifiedSkill(
            id=gen_skill.skill_id,
            name=gen_skill.skill_id,  # Use skill_id as unique name
            kind=SkillKind.RUNTIME,
            version="1",  # Agent skills don't have explicit versions
            description=gen_skill.description,
            capabilities=[],
            tools=tools,
            instructions=instructions,
            policies=[],
            dependencies=[],
            test_cases=[],
            tags=[gen_skill.skill_type, gen_skill.platform],
            domain=gen_skill.platform,
            effectiveness=EffectivenessMetrics(),
            metadata=metadata,
            author="agent-generator",
            status=gen_skill.status,
            created_at=gen_skill.created_at,
            updated_at=gen_skill.created_at,
        )

    def _convert_from_unified(self, unified_skill: UnifiedSkill) -> GeneratedSkill:
        """Convert unified Skill back to GeneratedSkill format."""
        # Extract metadata
        meta = unified_skill.metadata
        files_data = meta.get("files", [])
        files = [
            GeneratedFile(
                path=f["path"],
                content=f["content"],
                is_new=f["is_new"],
                diff=f.get("diff"),
            )
            for f in files_data
        ]

        # Get the original skill name from metadata (skill_id was used as name in unified)
        original_name = meta.get("skill_name", unified_skill.name)

        return GeneratedSkill(
            skill_id=unified_skill.id,
            gap_id=meta.get("gap_id", ""),
            platform=meta.get("platform", "adk"),
            skill_type=meta.get("skill_type", "tool"),
            name=original_name,  # Use original name from metadata
            description=unified_skill.description,
            source_code=meta.get("source_code"),
            config_yaml=meta.get("config_yaml"),
            files=files,
            eval_criteria=meta.get("eval_criteria", []),
            estimated_improvement=meta.get("estimated_improvement", 0.0),
            confidence=meta.get("confidence", "medium"),
            status=unified_skill.status,
            review_notes=meta.get("review_notes", ""),
            created_at=unified_skill.created_at,
        )

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def save(self, skill: GeneratedSkill) -> None:
        """Store a generated skill."""
        unified_skill = self._convert_to_unified(skill)

        # Try to get existing skill
        existing = self._unified_store.get(skill.skill_id)
        if existing:
            # Update existing
            self._unified_store.update(unified_skill)
        else:
            # Create new
            self._unified_store.create(unified_skill)

    def get(self, skill_id: str) -> GeneratedSkill | None:
        """Retrieve a skill by ID."""
        unified_skill = self._unified_store.get(skill_id)
        if unified_skill is None:
            return None

        # Only return if it's a RUNTIME skill
        if unified_skill.kind != SkillKind.RUNTIME:
            return None

        return self._convert_from_unified(unified_skill)

    def list(self, status: str | None = None, platform: str | None = None) -> list[GeneratedSkill]:
        """List skills with optional filters."""
        # List from unified store
        domain = platform  # platform maps to domain
        unified_skills = self._unified_store.list(kind=SkillKind.RUNTIME, domain=domain, status=status)

        # Convert to old format
        return [self._convert_from_unified(s) for s in unified_skills]

    def approve(self, skill_id: str) -> bool:
        """Mark a skill as approved."""
        return self._update_status(skill_id, "approved")

    def reject(self, skill_id: str, reason: str = "") -> bool:
        """Mark a skill as rejected."""
        skill = self.get(skill_id)
        if skill is None:
            return False

        skill.status = "rejected"
        skill.review_notes = reason
        self.save(skill)
        return True

    def list_by_gap(self, gap_id: str) -> list[GeneratedSkill]:
        """List all skills generated for a specific gap."""
        # Get all RUNTIME skills and filter by gap_id in metadata
        all_skills = self._unified_store.list(kind=SkillKind.RUNTIME)
        matching = [s for s in all_skills if s.metadata.get("gap_id") == gap_id]

        # Sort by created_at descending
        matching.sort(key=lambda s: s.created_at, reverse=True)

        return [self._convert_from_unified(s) for s in matching]

    def save_gap(self, gap: Any) -> None:
        """Store a SkillGap for reference."""
        gap_data = gap.to_dict()
        self._gap_store[gap.gap_id] = gap_data

        # Also store in any related skills
        skills = self.list_by_gap(gap.gap_id)
        for skill in skills:
            unified_skill = self._convert_to_unified(skill)
            unified_skill.metadata["gap_data"] = gap_data
            self._unified_store.update(unified_skill)

    def list_gaps(self) -> list[dict[str, Any]]:
        """List all stored skill gaps."""
        # Return gaps in reverse chronological order
        gaps = list(self._gap_store.values())
        gaps.sort(key=lambda g: g.get("created_at", 0), reverse=True)
        return gaps

    def _update_status(self, skill_id: str, status: str) -> bool:
        """Update skill status."""
        skill = self.get(skill_id)
        if skill is None:
            return False

        skill.status = status
        self.save(skill)
        return True

    # ------------------------------------------------------------------
    # Coordinator artifact ingestion
    # ------------------------------------------------------------------

    def save_from_coordinator_artifact(self, artifact: dict[str, Any]) -> GeneratedSkill:
        """Persist a ``generated_skill`` artifact emitted by the coordinator.

        The coordinator ``SkillAuthorWorker`` emits artifacts that serialize
        a :class:`GeneratedSkill` via ``to_dict()``. This helper rehydrates
        the record and saves it so ``/skills generate <slug>`` → store
        stays a single API call.
        """
        if not isinstance(artifact, dict):
            raise TypeError("save_from_coordinator_artifact expects a dict artifact")
        files_payload = artifact.get("files") or []
        files = [
            GeneratedFile(
                path=str(item.get("path", "")),
                content=str(item.get("content", "")),
                is_new=bool(item.get("is_new", True)),
                diff=item.get("diff"),
            )
            for item in files_payload
            if isinstance(item, dict)
        ]
        skill = GeneratedSkill(
            skill_id=str(artifact.get("skill_id") or ""),
            gap_id=str(artifact.get("gap_id") or ""),
            platform=str(artifact.get("platform") or "adk"),
            skill_type=str(artifact.get("skill_type") or "tool"),
            name=str(artifact.get("name") or artifact.get("skill_id") or "skill"),
            description=str(artifact.get("description") or ""),
            source_code=artifact.get("source_code"),
            config_yaml=artifact.get("config_yaml"),
            files=files,
            eval_criteria=list(artifact.get("eval_criteria") or []),
            estimated_improvement=float(artifact.get("estimated_improvement", 0.0) or 0.0),
            confidence=str(artifact.get("confidence") or "medium"),
            status=str(artifact.get("status") or "draft"),
            review_notes=str(artifact.get("review_notes") or ""),
        )
        if not skill.skill_id:
            raise ValueError("Coordinator artifact missing skill_id")
        self.save(skill)
        return skill
