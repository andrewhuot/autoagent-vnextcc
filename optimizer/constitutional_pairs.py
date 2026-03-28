"""Constitutional AI pair generation — revisions and batch processing."""

from __future__ import annotations

from typing import Any

from optimizer.constitution import Constitution, ConstitutionalPrinciple, ConstitutionalChecker


class ConstitutionalPairGenerator:
    """Generate preference pairs via Constitutional AI critique-revision cycles."""

    # ------------------------------------------------------------------
    # From violations
    # ------------------------------------------------------------------

    def generate_from_violations(
        self, violations: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Convert pre-computed violation dicts into preference pairs.

        Each violation must contain at minimum:
        ``input_text``, ``rejected`` (the offending response), and
        ``principle_id`` / ``principle_name`` / ``description``.
        """
        pairs: list[dict[str, Any]] = []
        for v in violations:
            input_text = v.get("input_text", "")
            rejected = v.get("rejected", v.get("response", ""))
            if not (input_text and rejected):
                continue
            chosen = (
                f"[REVISED — {v.get('principle_name', 'principle')}] "
                f"A response that respects '{v.get('description', '')}': "
                + rejected
            )
            pairs.append(
                {
                    "input_text": input_text,
                    "chosen": chosen,
                    "rejected": rejected,
                    "principle_id": v.get("principle_id", ""),
                    "category": v.get("category", ""),
                    "hard_violation": v.get("hard_violation", False),
                }
            )
        return pairs

    # ------------------------------------------------------------------
    # Single revision
    # ------------------------------------------------------------------

    def generate_revision(
        self,
        input_text: str,
        bad_response: str,
        principle: ConstitutionalPrinciple,
    ) -> dict[str, Any]:
        """Produce a preference pair dict for a single principle violation.

        In production this would call a stronger model to rewrite
        *bad_response*; here we produce a structured revision stub.
        """
        revision = (
            f"[REVISED per '{principle.name}'] "
            f"This response has been rewritten to comply with: "
            f'"{principle.description}". '
            f"Revised version of: {bad_response}"
        )
        return {
            "input_text": input_text,
            "chosen": revision,
            "rejected": bad_response,
            "principle_id": principle.principle_id,
            "principle_name": principle.name,
            "category": principle.category,
            "priority": principle.priority,
        }

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------

    def batch_generate(
        self,
        conversations: list[dict[str, Any]],
        constitution: Constitution,
    ) -> list[dict[str, Any]]:
        """Check every conversation against *constitution* and emit pairs.

        Each conversation must have ``input`` (str) and ``output`` (str) keys.
        Conversations with no violations are skipped.
        """
        checker = ConstitutionalChecker(constitution)
        all_pairs: list[dict[str, Any]] = []

        for conv in conversations:
            input_text = conv.get("input", conv.get("input_text", ""))
            output_text = conv.get("output", conv.get("output_text", ""))
            if not (input_text and output_text):
                continue

            violations = checker.check_response(input_text, output_text)
            for violation in violations:
                # Look up the principle object for richer revision
                principle_obj = next(
                    (
                        p
                        for p in constitution.principles
                        if p.principle_id == violation["principle_id"]
                    ),
                    None,
                )
                if principle_obj is None:
                    continue
                pair = self.generate_revision(input_text, output_text, principle_obj)
                pair["conversation_metadata"] = {
                    k: v
                    for k, v in conv.items()
                    if k not in {"input", "output", "input_text", "output_text"}
                }
                all_pairs.append(pair)

        return all_pairs
