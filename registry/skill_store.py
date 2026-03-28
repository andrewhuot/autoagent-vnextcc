"""SQLite-backed store for executable skills (Track A).

MIGRATION NOTE: This is now a backward-compatible wrapper around core/skills/store.
The old API surface is preserved for compatibility, but all data is stored in the
unified skill store format under the hood.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.skills.store import SkillStore as UnifiedSkillStore
from core.skills.types import (
    EffectivenessMetrics,
    EvalCriterion as UnifiedEvalCriterion,
    MutationOperator,
    Skill as UnifiedSkill,
    SkillExample as UnifiedSkillExample,
    SkillKind,
    TriggerCondition as UnifiedTriggerCondition,
)
from registry.skill_types import (
    EvalCriterion,
    MutationTemplate,
    Skill,
    SkillExample,
    TriggerCondition,
)


class SkillStore:
    """Backward-compatible wrapper around unified SkillStore.

    This maintains the old Track A API while using the unified store underneath.
    All old skills are converted to the BUILD kind in the unified format.
    """

    def __init__(self, db_path: str = "registry.db") -> None:
        """Initialize the skill store.

        Args:
            db_path: Path to SQLite database file.
        """
        self._db_path = db_path
        legacy_skills = self._extract_legacy_registry_skills(db_path)
        self._unified_store = UnifiedSkillStore(db_path)
        for old_skill in legacy_skills:
            unified_skill = self._convert_to_unified(old_skill)
            existing = self._unified_store.get_by_name(unified_skill.name, version=unified_skill.version)
            if existing is None:
                self._unified_store.create(unified_skill)

    def _extract_legacy_registry_skills(self, db_path: str) -> list[Skill]:
        """Read and clear legacy Track A rows if the DB uses the old schema.

        WHY: Older registry databases used an `executable_skills` table without
        the unified columns (`id`, `kind`, `domain`, `updated_at`). The unified
        store expects the new schema name, so we stage legacy rows in memory,
        drop the old table, then let unified initialization recreate tables.
        """
        path = Path(db_path)
        if not path.exists():
            return []

        conn = sqlite3.connect(db_path)
        try:
            table_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='executable_skills' LIMIT 1"
            ).fetchone()
            if table_exists is None:
                return []

            columns = {row[1] for row in conn.execute("PRAGMA table_info(executable_skills)").fetchall()}
            is_legacy = "kind" not in columns and {"name", "version", "data", "category", "platform"}.issubset(columns)
            if not is_legacy:
                return []

            skills: list[Skill] = []
            rows = conn.execute("SELECT data FROM executable_skills").fetchall()
            for (payload,) in rows:
                try:
                    data = json.loads(payload)
                    skills.append(Skill.from_dict(data))
                except Exception:
                    # Ignore malformed legacy rows; keep migration best-effort.
                    continue

            conn.execute("DROP TABLE IF EXISTS executable_skills")
            conn.commit()
            return skills
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def _convert_to_unified(self, old_skill: Skill) -> UnifiedSkill:
        """Convert old Track A skill format to unified format."""
        # Convert mutations
        mutations = [
            MutationOperator(
                name=m.name,
                description=m.description,
                target_surface=m.target_surface,
                operator_type=m.mutation_type,
                template=m.template,
                parameters=m.parameters,
                risk_level="low",  # Default, not in old schema
            )
            for m in old_skill.mutations
        ]

        # Convert triggers
        triggers = [
            UnifiedTriggerCondition(
                failure_family=t.failure_family,
                metric_name=t.metric_name,
                threshold=t.threshold,
                operator=t.operator,
                blame_pattern=t.blame_pattern,
            )
            for t in old_skill.triggers
        ]

        # Convert eval criteria
        eval_criteria = [
            UnifiedEvalCriterion(
                metric=e.metric,
                target=e.target,
                operator=e.operator,
                weight=e.weight,
            )
            for e in old_skill.eval_criteria
        ]

        # Convert examples
        examples = [
            UnifiedSkillExample(
                name=ex.name,
                description=ex.context,
                before=ex.before,
                after=ex.after,
                improvement=ex.improvement,
                context=ex.context,
            )
            for ex in old_skill.examples
        ]

        # Convert effectiveness metrics
        effectiveness = EffectivenessMetrics(
            times_applied=old_skill.times_applied,
            success_count=int(old_skill.success_rate * old_skill.times_applied)
            if old_skill.times_applied > 0
            else 0,
            success_rate=old_skill.success_rate,
            avg_improvement=old_skill.proven_improvement or 0.0,
            total_improvement=(old_skill.proven_improvement or 0.0) * old_skill.times_applied
            if old_skill.times_applied > 0
            else 0.0,
            last_applied=None,  # Not tracked in old schema
        )

        # Build unified skill
        # Use name-version as ID for deterministic lookups
        skill_id = f"{old_skill.name}-v{old_skill.version}"

        return UnifiedSkill(
            id=skill_id,
            name=old_skill.name,
            kind=SkillKind.BUILD,
            version=str(old_skill.version),
            description=old_skill.description,
            capabilities=old_skill.target_surfaces,  # Map target_surfaces to capabilities
            mutations=mutations,
            triggers=triggers,
            eval_criteria=eval_criteria,
            guardrails=old_skill.guardrails,
            examples=examples,
            tools=[],  # No tools in old schema
            instructions="",  # No instructions in old schema
            policies=[],  # No policies in old schema
            dependencies=[],  # No dependencies in old schema
            test_cases=[],  # No test cases in old schema
            tags=old_skill.tags,
            domain=old_skill.category,  # Map category to domain
            effectiveness=effectiveness,
            metadata={
                "platform": old_skill.platform,
                "target_surfaces": old_skill.target_surfaces,
            },
            author=old_skill.author,
            status=old_skill.status,
            created_at=old_skill.created_at,
            updated_at=old_skill.created_at,
        )

    def _convert_from_unified(self, unified_skill: UnifiedSkill) -> Skill:
        """Convert unified skill format back to old Track A format."""
        # Convert mutations
        mutations = [
            MutationTemplate(
                name=m.name,
                mutation_type=m.operator_type,
                target_surface=m.target_surface,
                description=m.description,
                template=m.template,
                parameters=m.parameters,
            )
            for m in unified_skill.mutations
        ]

        # Convert triggers
        triggers = [
            TriggerCondition(
                failure_family=t.failure_family,
                metric_name=t.metric_name,
                threshold=t.threshold,
                operator=t.operator,
                blame_pattern=t.blame_pattern,
            )
            for t in unified_skill.triggers
        ]

        # Convert eval criteria
        eval_criteria = [
            EvalCriterion(
                metric=e.metric,
                target=e.target,
                operator=e.operator,
                weight=e.weight,
            )
            for e in unified_skill.eval_criteria
        ]

        # Convert examples
        examples = [
            SkillExample(
                name=ex.name,
                surface=unified_skill.metadata.get("target_surfaces", ["prompt"])[0]
                if unified_skill.metadata.get("target_surfaces")
                else "prompt",
                before=ex.before,
                after=ex.after,
                improvement=ex.improvement,
                context=ex.context,
            )
            for ex in unified_skill.examples
        ]

        # Extract old fields from metadata or use defaults
        platform = unified_skill.metadata.get("platform", "universal")
        target_surfaces = unified_skill.metadata.get("target_surfaces", unified_skill.capabilities)

        return Skill(
            name=unified_skill.name,
            version=int(unified_skill.version),
            description=unified_skill.description,
            category=unified_skill.domain,
            platform=platform,
            target_surfaces=target_surfaces,
            mutations=mutations,
            examples=examples,
            guardrails=unified_skill.guardrails,
            eval_criteria=eval_criteria,
            triggers=triggers,
            author=unified_skill.author,
            tags=unified_skill.tags,
            created_at=unified_skill.created_at,
            proven_improvement=unified_skill.effectiveness.avg_improvement
            if unified_skill.effectiveness.avg_improvement > 0
            else None,
            times_applied=unified_skill.effectiveness.times_applied,
            success_rate=unified_skill.effectiveness.success_rate,
            status=unified_skill.status,
        )

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def register(self, skill: Skill) -> tuple[str, int]:
        """Insert skill, auto-incrementing the version for the same name."""
        # Find the next version number for this skill name
        existing_skills = self._unified_store.list(kind=SkillKind.BUILD)
        max_version = 0
        for s in existing_skills:
            if s.name == skill.name:
                try:
                    v = int(s.version)
                    if v > max_version:
                        max_version = v
                except ValueError:
                    pass

        next_version = max_version + 1
        skill.version = next_version

        # Convert to unified format and store
        unified_skill = self._convert_to_unified(skill)
        self._unified_store.create(unified_skill)

        return (skill.name, skill.version)

    def get(self, name: str, version: int | None = None) -> Skill | None:
        """Return a skill by name, defaulting to the latest version."""
        version_str = str(version) if version is not None else None
        unified_skill = self._unified_store.get_by_name(name, version=version_str)

        if unified_skill is None:
            return None

        # Only return if it's a BUILD skill
        if unified_skill.kind != SkillKind.BUILD:
            return None

        return self._convert_from_unified(unified_skill)

    # ------------------------------------------------------------------
    # Listing and search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        category: str | None = None,
        platform: str | None = None,
    ) -> list[Skill]:
        """LIKE search on name and JSON data blob. Returns latest version of each match."""
        # Search in unified store
        all_matches = self._unified_store.search(query, kind=SkillKind.BUILD)

        # Filter by category (domain in unified)
        if category is not None:
            all_matches = [s for s in all_matches if s.domain == category]

        # Filter by platform (in metadata)
        if platform is not None:
            all_matches = [s for s in all_matches if s.metadata.get("platform") == platform]

        # Group by name and keep only latest version
        latest_by_name: dict[str, UnifiedSkill] = {}
        for skill in all_matches:
            if skill.name not in latest_by_name:
                latest_by_name[skill.name] = skill
            else:
                try:
                    if int(skill.version) > int(latest_by_name[skill.name].version):
                        latest_by_name[skill.name] = skill
                except ValueError:
                    pass

        return [self._convert_from_unified(s) for s in latest_by_name.values()]

    def list(
        self,
        category: str | None = None,
        platform: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
    ) -> list[Skill]:
        """Return latest version of each skill, with optional filters."""
        # List from unified store
        domain = category  # category maps to domain
        all_skills = self._unified_store.list(
            kind=SkillKind.BUILD, domain=domain, tags=tags, status=status
        )

        # Filter by platform (in metadata)
        if platform is not None:
            all_skills = [s for s in all_skills if s.metadata.get("platform") == platform]

        # Group by name and keep only latest version
        latest_by_name: dict[str, UnifiedSkill] = {}
        for skill in all_skills:
            if skill.name not in latest_by_name:
                latest_by_name[skill.name] = skill
            else:
                try:
                    if int(skill.version) > int(latest_by_name[skill.name].version):
                        latest_by_name[skill.name] = skill
                except ValueError:
                    pass

        return [self._convert_from_unified(s) for s in latest_by_name.values()]

    # ------------------------------------------------------------------
    # Recommendation engine
    # ------------------------------------------------------------------

    def recommend(
        self,
        failure_family: str | None = None,
        metrics: dict[str, float] | None = None,
    ) -> list[Skill]:
        """Return skills whose triggers match the given failure family or metric thresholds."""
        # Use unified store's recommendation engine
        unified_skills = self._unified_store.recommend(
            failure_family=failure_family, metrics=metrics, kind=SkillKind.BUILD
        )

        # Convert to old format
        return [self._convert_from_unified(s) for s in unified_skills]

    # ------------------------------------------------------------------
    # Outcome tracking
    # ------------------------------------------------------------------

    def record_outcome(self, skill_name: str, improvement: float, success: bool) -> None:
        """Record an outcome and recalculate stats on the latest skill version."""
        # Get the latest version of this skill
        skill = self.get(skill_name)
        if skill is None:
            return

        # Get the unified skill ID
        skill_id = f"{skill.name}-v{skill.version}"

        # Record outcome in unified store
        self._unified_store.record_outcome(skill_id, improvement, success)

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def top_performers(self, n: int = 10) -> list[Skill]:
        """Return top-n active skills by proven_improvement * success_rate."""
        # Use unified store's top performers
        unified_skills = self._unified_store.get_top_performers(n=n, kind=SkillKind.BUILD)

        # Convert to old format
        return [self._convert_from_unified(s) for s in unified_skills]

    # ------------------------------------------------------------------
    # SKILL.md import / export
    # ------------------------------------------------------------------

    def import_from_md(self, path: str) -> Skill:
        """Import a skill from a SKILL.md file or directory and register it.

        If a skill with the same name already exists in the store it will **not**
        be overwritten; the existing skill is returned instead.

        Args:
            path: Path to a ``.md`` file or a directory containing ``SKILL.md``.

        Returns:
            The imported (or already-existing) :class:`~registry.skill_types.Skill`.

        Raises:
            FileNotFoundError: If *path* does not exist or contains no SKILL.md.
        """
        from registry.skill_loader import load_from_skill_md  # noqa: PLC0415

        skill = load_from_skill_md(path)

        # Only register if the skill isn't already present
        existing = self.get(skill.name)
        if existing is None:
            self.register(skill)
            # Re-fetch to get the auto-assigned version
            registered = self.get(skill.name)
            return registered or skill

        return existing

    def export_to_md(self, skill_name: str, output_path: str) -> str:
        """Export a skill to SKILL.md format.

        Args:
            skill_name: Name of the skill to export (latest version used).
            output_path: Destination file path (e.g. ``/tmp/my-skill.md``).
                If the path ends with a path separator or names an existing
                directory a ``SKILL.md`` file is written inside that directory.

        Returns:
            The absolute path of the written file.

        Raises:
            KeyError: If no skill with *skill_name* is found in the store.
        """
        from registry.skill_md import SkillMdSerializer  # noqa: PLC0415

        skill = self.get(skill_name)
        if skill is None:
            raise KeyError(f"Skill not found: {skill_name!r}")

        import os  # noqa: PLC0415

        # Resolve directory vs. file path
        if os.path.isdir(output_path) or output_path.endswith(os.sep):
            os.makedirs(output_path, exist_ok=True)
            output_path = os.path.join(output_path, "SKILL.md")
        else:
            parent = os.path.dirname(os.path.abspath(output_path))
            os.makedirs(parent, exist_ok=True)

        serializer = SkillMdSerializer()
        serializer.serialize_to_file(skill, output_path)
        return os.path.abspath(output_path)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying unified store."""
        self._unified_store.close()
