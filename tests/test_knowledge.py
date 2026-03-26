"""Tests for knowledge mining and knowledge store."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from logger.store import ConversationRecord, ConversationStore
from observer.knowledge_miner import KnowledgeMiner, KnowledgePattern
from observer.knowledge_store import KnowledgeStore


class TestKnowledgeStore:
    """Test knowledge store CRUD operations."""

    def test_create_and_get_entry(self, tmp_path: Path):
        """Test creating and retrieving a knowledge entry."""
        store = KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))

        entry = {
            "pattern_id": "test-001",
            "pattern_type": "tool_usage",
            "description": "Successful tool sequence",
            "evidence_conversations": ["conv-1", "conv-2", "conv-3"],
            "confidence": 0.85,
            "applicable_intents": ["billing"],
            "suggested_application": "tool_ordering",
            "status": "draft",
        }

        store.create(entry)

        retrieved = store.get("test-001")
        assert retrieved is not None
        assert retrieved["pattern_id"] == "test-001"
        assert retrieved["pattern_type"] == "tool_usage"
        assert retrieved["confidence"] == 0.85
        assert len(retrieved["evidence_conversations"]) == 3

    def test_list_entries(self, tmp_path: Path):
        """Test listing knowledge entries."""
        store = KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))

        # Create multiple entries
        for i in range(5):
            entry = {
                "pattern_id": f"test-{i:03d}",
                "pattern_type": "tool_usage",
                "description": f"Pattern {i}",
                "evidence_conversations": [f"conv-{i}"],
                "confidence": 0.5 + (i * 0.1),
                "applicable_intents": ["general"],
                "suggested_application": "tool_ordering",
                "status": "draft",
            }
            store.create(entry)

        entries = store.list()
        assert len(entries) == 5

    def test_list_entries_with_status_filter(self, tmp_path: Path):
        """Test listing entries filtered by status."""
        store = KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))

        # Create entries with different statuses
        for i in range(3):
            store.create({
                "pattern_id": f"draft-{i}",
                "pattern_type": "tool_usage",
                "description": f"Draft pattern {i}",
                "evidence_conversations": [],
                "confidence": 0.7,
                "applicable_intents": [],
                "suggested_application": "tool_ordering",
                "status": "draft",
            })

        for i in range(2):
            store.create({
                "pattern_id": f"reviewed-{i}",
                "pattern_type": "phrasing",
                "description": f"Reviewed pattern {i}",
                "evidence_conversations": [],
                "confidence": 0.8,
                "applicable_intents": [],
                "suggested_application": "few_shot",
                "status": "reviewed",
            })

        draft_entries = store.list(status="draft")
        assert len(draft_entries) == 3

        reviewed_entries = store.list(status="reviewed")
        assert len(reviewed_entries) == 2

    def test_update_status(self, tmp_path: Path):
        """Test updating entry status."""
        store = KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))

        entry = {
            "pattern_id": "test-status",
            "pattern_type": "tool_usage",
            "description": "Test pattern",
            "evidence_conversations": [],
            "confidence": 0.7,
            "applicable_intents": [],
            "suggested_application": "tool_ordering",
            "status": "draft",
        }
        store.create(entry)

        # Update status
        success = store.update_status("test-status", "reviewed")
        assert success

        # Verify update
        updated = store.get("test-status")
        assert updated["status"] == "reviewed"

    def test_mark_applied(self, tmp_path: Path):
        """Test marking entry as applied with impact score."""
        store = KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))

        entry = {
            "pattern_id": "test-apply",
            "pattern_type": "tool_usage",
            "description": "Test pattern",
            "evidence_conversations": [],
            "confidence": 0.8,
            "applicable_intents": [],
            "suggested_application": "tool_ordering",
            "status": "reviewed",
        }
        store.create(entry)

        # Mark as applied with impact score
        success = store.mark_applied("test-apply", impact_score=0.05)
        assert success

        # Verify update
        updated = store.get("test-apply")
        assert updated["status"] == "applied"
        assert updated["applied_at"] is not None
        assert updated["impact_score"] == 0.05

    def test_get_nonexistent_entry(self, tmp_path: Path):
        """Test getting nonexistent entry returns None."""
        store = KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))
        entry = store.get("nonexistent")
        assert entry is None


class TestKnowledgeMiner:
    """Test knowledge mining functionality."""

    def test_mine_successes_filters_by_score(self, tmp_path: Path):
        """Test that mine_successes filters conversations by score."""
        conv_store = ConversationStore(db_path=str(tmp_path / "conversations.db"))

        # Add successful conversations
        for i in range(5):
            conv_store.log(
                ConversationRecord(
                    conversation_id=f"success-{i}",
                    session_id=f"sess-{i}",
                    timestamp=time.time(),
                    user_message=f"Request {i}",
                    response=f"Response {i}",
                    success=True,
                    safety_violations=0,
                    latency_ms=500,
                    cost=0.005,
                )
            )

        # Add failed conversations
        for i in range(3):
            conv_store.log(
                ConversationRecord(
                    conversation_id=f"failure-{i}",
                    session_id=f"sess-{i}",
                    timestamp=time.time(),
                    user_message=f"Request {i}",
                    response=f"Response {i}",
                    success=False,
                    safety_violations=0,
                    latency_ms=500,
                    cost=0.005,
                )
            )

        miner = KnowledgeMiner(conv_store)
        successful = miner.mine_successes(min_score=0.9, limit=10)

        # Should only get successful conversations
        assert len(successful) == 5
        assert all(conv.success for conv in successful)

    def test_extract_tool_patterns(self, tmp_path: Path):
        """Test extraction of tool usage patterns."""
        conv_store = ConversationStore(db_path=str(tmp_path / "conversations.db"))

        # Add conversations with tool calls
        for i in range(5):
            conv_store.log(
                ConversationRecord(
                    conversation_id=f"conv-{i}",
                    session_id=f"sess-{i}",
                    timestamp=time.time(),
                    user_message="Billing question",
                    response="Here's your answer",
                    success=True,
                    safety_violations=0,
                    tool_calls=["check_account", "query_billing"],
                    latency_ms=500,
                    cost=0.005,
                )
            )

        miner = KnowledgeMiner(conv_store)
        successful = miner.mine_successes()
        patterns = miner.extract_patterns(successful)

        # Should find tool usage pattern
        assert len(patterns) > 0
        tool_patterns = [p for p in patterns if p.pattern_type == "tool_usage"]
        assert len(tool_patterns) > 0

    def test_extract_patterns_requires_minimum_evidence(self, tmp_path: Path):
        """Test that patterns require minimum evidence count."""
        conv_store = ConversationStore(db_path=str(tmp_path / "conversations.db"))

        # Add only 2 conversations with same tool sequence (below threshold of 3)
        for i in range(2):
            conv_store.log(
                ConversationRecord(
                    conversation_id=f"conv-{i}",
                    session_id=f"sess-{i}",
                    timestamp=time.time(),
                    user_message="Question",
                    response="Answer",
                    success=True,
                    safety_violations=0,
                    tool_calls=["tool_a", "tool_b"],
                    latency_ms=500,
                    cost=0.005,
                )
            )

        miner = KnowledgeMiner(conv_store)
        successful = miner.mine_successes()
        patterns = miner.extract_patterns(successful)

        # Should not create pattern with insufficient evidence
        tool_patterns = [p for p in patterns if p.pattern_type == "tool_usage"]
        assert len(tool_patterns) == 0

    def test_generate_knowledge_entries(self, tmp_path: Path):
        """Test generation of knowledge entries from patterns."""
        conv_store = ConversationStore(db_path=str(tmp_path / "conversations.db"))

        # Add conversations
        for i in range(5):
            conv_store.log(
                ConversationRecord(
                    conversation_id=f"conv-{i}",
                    session_id=f"sess-{i}",
                    timestamp=time.time(),
                    user_message="Question",
                    response="Answer",
                    success=True,
                    safety_violations=0,
                    tool_calls=["tool_a"],
                    latency_ms=500,
                    cost=0.005,
                )
            )

        miner = KnowledgeMiner(conv_store)
        successful = miner.mine_successes()
        patterns = miner.extract_patterns(successful)
        entries = miner.generate_knowledge_entries(patterns)

        # Verify entries structure
        for entry in entries:
            assert "pattern_id" in entry
            assert "pattern_type" in entry
            assert "description" in entry
            assert "evidence_conversations" in entry
            assert "confidence" in entry
            assert "suggested_application" in entry
            assert entry["status"] == "draft"

    def test_knowledge_pattern_confidence(self, tmp_path: Path):
        """Test that confidence is calculated based on evidence count."""
        conv_store = ConversationStore(db_path=str(tmp_path / "conversations.db"))

        # Add many successful conversations with same tool sequence
        for i in range(15):
            conv_store.log(
                ConversationRecord(
                    conversation_id=f"conv-{i}",
                    session_id=f"sess-{i}",
                    timestamp=time.time(),
                    user_message="Question",
                    response="Answer",
                    success=True,
                    safety_violations=0,
                    tool_calls=["popular_tool"],
                    latency_ms=500,
                    cost=0.005,
                )
            )

        miner = KnowledgeMiner(conv_store)
        successful = miner.mine_successes()
        patterns = miner.extract_patterns(successful)

        # Patterns with more evidence should have higher confidence
        assert len(patterns) > 0
        for pattern in patterns:
            assert 0.0 <= pattern.confidence <= 1.0


class TestKnowledgeMiningIntegration:
    """Integration tests for full knowledge mining flow."""

    def test_full_mining_workflow(self, tmp_path: Path):
        """Test complete workflow: mine → extract → store."""
        conv_store = ConversationStore(db_path=str(tmp_path / "conversations.db"))
        knowledge_store = KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))

        # Create successful conversations
        for i in range(10):
            conv_store.log(
                ConversationRecord(
                    conversation_id=f"conv-{i}",
                    session_id=f"sess-{i}",
                    timestamp=time.time(),
                    user_message="Billing question",
                    response="Here's the answer",
                    success=True,
                    safety_violations=0,
                    tool_calls=["check_account", "query_billing"],
                    latency_ms=400,
                    cost=0.003,
                )
            )

        # Mine and extract
        miner = KnowledgeMiner(conv_store)
        successful = miner.mine_successes()
        patterns = miner.extract_patterns(successful)
        entries = miner.generate_knowledge_entries(patterns)

        # Store entries
        for entry in entries:
            knowledge_store.create(entry)

        # Verify stored
        stored_entries = knowledge_store.list()
        assert len(stored_entries) > 0

        # Verify all are draft status
        assert all(e["status"] == "draft" for e in stored_entries)

    def test_apply_knowledge_entry_workflow(self, tmp_path: Path):
        """Test workflow for applying a knowledge entry."""
        knowledge_store = KnowledgeStore(db_path=str(tmp_path / "knowledge.db"))

        # Create entry
        entry = {
            "pattern_id": "workflow-test",
            "pattern_type": "tool_usage",
            "description": "Effective tool sequence",
            "evidence_conversations": ["conv-1", "conv-2", "conv-3"],
            "confidence": 0.9,
            "applicable_intents": ["billing"],
            "suggested_application": "tool_ordering",
            "status": "draft",
        }
        knowledge_store.create(entry)

        # Review and approve
        knowledge_store.update_status("workflow-test", "reviewed")
        reviewed = knowledge_store.get("workflow-test")
        assert reviewed["status"] == "reviewed"

        # Apply
        knowledge_store.mark_applied("workflow-test", impact_score=0.07)
        applied = knowledge_store.get("workflow-test")
        assert applied["status"] == "applied"
        assert applied["impact_score"] == 0.07
        assert applied["applied_at"] is not None
