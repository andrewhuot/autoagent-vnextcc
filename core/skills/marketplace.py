"""Skill marketplace for discovering, installing, and publishing skills.

This module provides a file-based marketplace that can be extended to HTTP in the future.
Skills are stored in ~/.autoagent/marketplace/ and can be browsed, searched, and installed.

Future enhancements:
- HTTP-based remote marketplace
- Skill ratings and reviews
- Dependency resolution
- Version conflict detection
- Signature verification
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

import yaml

from core.skills.loader import SkillLoader
from core.skills.store import SkillStore
from core.skills.types import Skill, SkillKind
from core.skills.validator import SkillValidator

logger = logging.getLogger(__name__)


class MarketplaceError(Exception):
    """Raised when marketplace operations fail."""

    pass


class SkillMarketplace:
    """Marketplace for discovering, installing, and publishing skills.

    The marketplace is file-based by default, storing skills in ~/.autoagent/marketplace/.
    Each skill is stored as a YAML file named {skill_id}.yaml.

    Metadata index is maintained in marketplace.json for fast browsing and searching.

    Example:
        ```python
        marketplace = SkillMarketplace()

        # Browse all skills
        all_skills = marketplace.browse()

        # Search for routing skills
        routing_skills = marketplace.search("routing", kind=SkillKind.BUILD)

        # Install a skill
        store = SkillStore()
        skill = marketplace.install("keyword_expansion", store)

        # Publish a skill
        marketplace.publish(skill)
        ```
    """

    def __init__(
        self,
        marketplace_dir: str | None = None,
        validator: SkillValidator | None = None,
    ) -> None:
        """Initialize the marketplace.

        Args:
            marketplace_dir: Directory for marketplace files. Defaults to ~/.autoagent/marketplace/
            validator: Optional validator instance. Creates default if None.
        """
        if marketplace_dir is None:
            marketplace_dir = str(Path.home() / ".autoagent" / "marketplace")

        self.marketplace_dir = Path(marketplace_dir)
        self.marketplace_dir.mkdir(parents=True, exist_ok=True)

        self.index_path = self.marketplace_dir / "marketplace.json"
        self.validator = validator or SkillValidator()
        self.loader = SkillLoader(validator=self.validator)

        # Initialize index if it doesn't exist
        if not self.index_path.exists():
            self._save_index({})

    # ------------------------------------------------------------------
    # Browsing and Discovery
    # ------------------------------------------------------------------

    def browse(
        self,
        kind: SkillKind | None = None,
        domain: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Browse available skills in the marketplace.

        Returns skill metadata (not full skill objects) for efficient browsing.

        Args:
            kind: Filter by skill kind (build/runtime)
            domain: Filter by domain (e.g., "customer-support", "sales")
            tags: Filter by tags (must have at least one matching tag)

        Returns:
            List of skill metadata dicts with:
            - id: Skill ID
            - name: Skill name
            - kind: Skill kind
            - version: Version string
            - description: Brief description
            - domain: Domain
            - tags: List of tags
            - author: Author
            - capabilities: List of capabilities
        """
        index = self._load_index()
        results: list[dict[str, Any]] = []

        for skill_id, metadata in index.items():
            # Apply filters
            if kind is not None and metadata.get("kind") != kind.value:
                continue

            if domain is not None and metadata.get("domain") != domain:
                continue

            if tags is not None:
                skill_tags = metadata.get("tags", [])
                if not any(tag in skill_tags for tag in tags):
                    continue

            results.append(metadata)

        return results

    def search(
        self,
        query: str,
        kind: SkillKind | None = None,
    ) -> list[dict[str, Any]]:
        """Search the marketplace for skills.

        Searches across:
        - Skill name
        - Description
        - Capabilities
        - Tags

        Args:
            query: Search query string (case-insensitive)
            kind: Optional filter by skill kind

        Returns:
            List of matching skill metadata dicts
        """
        index = self._load_index()
        query_lower = query.lower()
        results: list[dict[str, Any]] = []

        for skill_id, metadata in index.items():
            # Apply kind filter
            if kind is not None and metadata.get("kind") != kind.value:
                continue

            # Search in multiple fields
            searchable_text = " ".join([
                metadata.get("name", ""),
                metadata.get("description", ""),
                " ".join(metadata.get("capabilities", [])),
                " ".join(metadata.get("tags", [])),
            ]).lower()

            if query_lower in searchable_text:
                results.append(metadata)

        return results

    def get_metadata(self, skill_id: str) -> dict[str, Any] | None:
        """Get metadata for a specific skill.

        Args:
            skill_id: Skill ID

        Returns:
            Skill metadata dict, or None if not found
        """
        index = self._load_index()
        return index.get(skill_id)

    # ------------------------------------------------------------------
    # Installation
    # ------------------------------------------------------------------

    def install(self, source: str, store: SkillStore) -> Skill:
        """Install a skill from the marketplace or URL.

        Source can be:
        - Skill ID in marketplace (e.g., "keyword_expansion")
        - URL to YAML file (e.g., "https://example.com/skills/my_skill.yaml")
        - Local file path (e.g., "/path/to/skill.yaml")

        Args:
            source: Skill ID, URL, or file path
            store: SkillStore to install into

        Returns:
            The installed Skill instance

        Raises:
            MarketplaceError: If skill not found or installation fails
        """
        try:
            # Check if source is a URL
            if source.startswith("http://") or source.startswith("https://"):
                skill = self._install_from_url(source)
            # Check if source is a local file path
            elif "/" in source or "\\" in source or source.endswith(".yaml"):
                skill = self._install_from_file(source)
            # Otherwise, treat as marketplace skill ID
            else:
                skill = self._install_from_marketplace(source)

            # Validate before installing
            result = self.validator.validate(skill)
            if not result.is_valid:
                raise MarketplaceError(
                    f"Skill validation failed: {', '.join(result.errors)}"
                )

            # Install into store
            existing = store.get_by_name(skill.name, skill.version)
            if existing is not None:
                logger.info(
                    f"Skill {skill.name}@{skill.version} already exists in store. Skipping installation."
                )
                return existing

            skill_id = store.create(skill)
            logger.info(f"Installed skill {skill.name}@{skill.version} with ID {skill_id}")

            return skill

        except Exception as e:
            raise MarketplaceError(f"Failed to install skill from {source}: {e}") from e

    def _install_from_marketplace(self, skill_id: str) -> Skill:
        """Install a skill from the local marketplace directory."""
        skill_file = self.marketplace_dir / f"{skill_id}.yaml"

        if not skill_file.exists():
            raise MarketplaceError(f"Skill not found in marketplace: {skill_id}")

        skills = self.loader.load_from_yaml(str(skill_file))
        if not skills:
            raise MarketplaceError(f"No skills found in {skill_file}")

        # Return the first skill (marketplace files should contain exactly one skill)
        return skills[0]

    def _install_from_url(self, url: str) -> Skill:
        """Download and install a skill from a URL."""
        if not HAS_REQUESTS:
            raise MarketplaceError(
                "requests library is required for URL-based installation. "
                "Install it with: pip install requests"
            )

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            # Parse URL to get filename
            parsed_url = urlparse(url)
            filename = Path(parsed_url.path).name

            if not filename.endswith((".yaml", ".yml")):
                raise MarketplaceError(f"URL must point to a YAML file: {url}")

            # Save to temp file and load
            temp_file = self.marketplace_dir / f"temp_{filename}"
            try:
                temp_file.write_text(response.text, encoding="utf-8")
                skills = self.loader.load_from_yaml(str(temp_file))
                if not skills:
                    raise MarketplaceError(f"No skills found at {url}")
                return skills[0]
            finally:
                # Clean up temp file
                if temp_file.exists():
                    temp_file.unlink()

        except Exception as e:
            if "requests" in str(type(e).__module__):
                raise MarketplaceError(f"Failed to download skill from {url}: {e}") from e
            raise

    def _install_from_file(self, file_path: str) -> Skill:
        """Install a skill from a local file."""
        path = Path(file_path)
        if not path.exists():
            raise MarketplaceError(f"File not found: {file_path}")

        skills = self.loader.load_from_yaml(str(path))
        if not skills:
            raise MarketplaceError(f"No skills found in {file_path}")

        return skills[0]

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, skill: Skill, api_key: str | None = None) -> bool:
        """Publish a skill to the marketplace.

        For the file-based marketplace, this copies the skill to the marketplace directory
        and updates the index.

        In a future HTTP-based marketplace, the api_key would be used for authentication.

        Args:
            skill: Skill to publish
            api_key: Optional API key for authentication (unused in file-based marketplace)

        Returns:
            True if published successfully, False otherwise

        Raises:
            MarketplaceError: If validation fails or publishing fails
        """
        try:
            # Validate skill
            result = self.validator.validate(skill)
            if not result.is_valid:
                raise MarketplaceError(
                    f"Skill validation failed: {', '.join(result.errors)}"
                )

            if result.warnings:
                for warning in result.warnings:
                    logger.warning(f"Skill {skill.name}: {warning}")

            # Save skill to marketplace directory
            skill_file = self.marketplace_dir / f"{skill.id}.yaml"

            skill_data = {
                "skills": [skill.to_dict()]
            }

            with open(skill_file, "w") as f:
                yaml.dump(skill_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

            # Update index
            self._add_to_index(skill)

            logger.info(f"Published skill {skill.name}@{skill.version} to marketplace")
            return True

        except Exception as e:
            raise MarketplaceError(f"Failed to publish skill {skill.name}: {e}") from e

    # ------------------------------------------------------------------
    # Index Management
    # ------------------------------------------------------------------

    def _load_index(self) -> dict[str, dict[str, Any]]:
        """Load the marketplace index.

        Returns:
            Dictionary mapping skill_id to metadata
        """
        if not self.index_path.exists():
            return {}

        try:
            with open(self.index_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load marketplace index: {e}")
            return {}

    def _save_index(self, index: dict[str, dict[str, Any]]) -> None:
        """Save the marketplace index."""
        try:
            with open(self.index_path, "w") as f:
                json.dump(index, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save marketplace index: {e}")

    def _add_to_index(self, skill: Skill) -> None:
        """Add a skill to the marketplace index."""
        index = self._load_index()

        # Create metadata entry
        index[skill.id] = {
            "id": skill.id,
            "name": skill.name,
            "kind": skill.kind.value,
            "version": skill.version,
            "description": skill.description,
            "domain": skill.domain,
            "tags": skill.tags,
            "author": skill.author,
            "capabilities": skill.capabilities,
            "status": skill.status,
            "created_at": skill.created_at,
            "updated_at": skill.updated_at,
        }

        self._save_index(index)

    def rebuild_index(self) -> int:
        """Rebuild the marketplace index from all YAML files.

        Scans the marketplace directory and rebuilds the index from scratch.
        Useful if the index gets corrupted or out of sync.

        Returns:
            Number of skills indexed
        """
        index: dict[str, dict[str, Any]] = {}
        count = 0

        for skill_file in self.marketplace_dir.glob("*.yaml"):
            # Skip the temp files
            if skill_file.name.startswith("temp_"):
                continue

            try:
                skills = self.loader.load_from_yaml(str(skill_file))
                for skill in skills:
                    index[skill.id] = {
                        "id": skill.id,
                        "name": skill.name,
                        "kind": skill.kind.value,
                        "version": skill.version,
                        "description": skill.description,
                        "domain": skill.domain,
                        "tags": skill.tags,
                        "author": skill.author,
                        "capabilities": skill.capabilities,
                        "status": skill.status,
                        "created_at": skill.created_at,
                        "updated_at": skill.updated_at,
                    }
                    count += 1
            except Exception as e:
                logger.error(f"Failed to load {skill_file} during index rebuild: {e}")

        self._save_index(index)
        logger.info(f"Rebuilt marketplace index with {count} skills")
        return count

    # ------------------------------------------------------------------
    # Bulk Operations
    # ------------------------------------------------------------------

    def install_all(
        self,
        store: SkillStore,
        kind: SkillKind | None = None,
        domain: str | None = None,
    ) -> tuple[int, list[str]]:
        """Install all skills from the marketplace into a store.

        Args:
            store: SkillStore to install into
            kind: Optional filter by skill kind
            domain: Optional filter by domain

        Returns:
            Tuple of (num_installed, errors)
        """
        skills_metadata = self.browse(kind=kind, domain=domain)
        installed = 0
        errors: list[str] = []

        for metadata in skills_metadata:
            try:
                self.install(metadata["id"], store)
                installed += 1
            except MarketplaceError as e:
                errors.append(f"{metadata['id']}: {e}")
                logger.error(f"Failed to install {metadata['id']}: {e}")

        return installed, errors

    def export_marketplace(self, output_dir: str) -> int:
        """Export the entire marketplace to a directory.

        Useful for creating marketplace backups or distributions.

        Args:
            output_dir: Directory to export to

        Returns:
            Number of skills exported
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        count = 0
        for skill_file in self.marketplace_dir.glob("*.yaml"):
            if skill_file.name.startswith("temp_"):
                continue

            try:
                shutil.copy2(skill_file, output_path / skill_file.name)
                count += 1
            except Exception as e:
                logger.error(f"Failed to export {skill_file}: {e}")

        # Also copy the index
        if self.index_path.exists():
            shutil.copy2(self.index_path, output_path / "marketplace.json")

        logger.info(f"Exported {count} skills to {output_dir}")
        return count

    def import_marketplace(self, import_dir: str) -> int:
        """Import skills from a directory into the marketplace.

        Args:
            import_dir: Directory to import from

        Returns:
            Number of skills imported
        """
        import_path = Path(import_dir)
        if not import_path.exists():
            raise MarketplaceError(f"Import directory not found: {import_dir}")

        count = 0
        for skill_file in import_path.glob("*.yaml"):
            if skill_file.name.startswith("temp_"):
                continue

            try:
                # Load and validate
                skills = self.loader.load_from_yaml(str(skill_file))
                for skill in skills:
                    # Publish to marketplace
                    self.publish(skill)
                    count += 1
            except Exception as e:
                logger.error(f"Failed to import {skill_file}: {e}")

        logger.info(f"Imported {count} skills from {import_dir}")
        return count

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Get marketplace statistics.

        Returns:
            Dictionary with:
            - total_skills: Total number of skills
            - build_skills: Number of build-time skills
            - runtime_skills: Number of run-time skills
            - domains: List of domains
            - top_tags: Most common tags
        """
        index = self._load_index()

        build_count = sum(1 for m in index.values() if m.get("kind") == "build")
        runtime_count = sum(1 for m in index.values() if m.get("kind") == "runtime")

        domains = set(m.get("domain", "general") for m in index.values())

        # Count tags
        tag_counts: dict[str, int] = {}
        for metadata in index.values():
            for tag in metadata.get("tags", []):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

        top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            "total_skills": len(index),
            "build_skills": build_count,
            "runtime_skills": runtime_count,
            "domains": sorted(domains),
            "top_tags": [{"tag": tag, "count": count} for tag, count in top_tags],
        }
