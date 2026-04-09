"""Tests for curriculum generator (self-play feature)."""

import pytest
from optimizer.curriculum_generator import (
    CurriculumGenerator,
    CurriculumStore,
    FailureCluster,
    DifficultyTier,
)


def test_curriculum_generator_basic():
    """Test basic curriculum generation."""
    generator = CurriculumGenerator(prompts_per_cluster=2, adversarial_ratio=0.5)

    # Create test failure clusters
    clusters = [
        FailureCluster(
            failure_family="routing_error",
            count=10,
            examples=[
                {"user_message": "help me with routing", "specialist_used": "support", "error": "wrong_specialist"}
            ],
            categories=["routing_error"],
            pass_rate=0.7,  # Easy
        ),
        FailureCluster(
            failure_family="tool_failure",
            count=5,
            examples=[
                {"user_message": "lookup order 123", "specialist_used": "support", "error": "tool_not_found"}
            ],
            categories=["tool_failure"],
            pass_rate=0.4,  # Medium
        ),
    ]

    # Generate curriculum
    batch = generator.generate_curriculum(clusters)

    # Verify batch structure
    assert batch.batch_id.startswith("curriculum_")
    assert len(batch.prompts) > 0
    assert len(batch.source_clusters) == 2
    assert "routing_error" in batch.source_clusters
    assert "tool_failure" in batch.source_clusters

    # Verify tier distribution
    assert "easy" in batch.tier_distribution
    assert "medium" in batch.tier_distribution
    assert "adversarial" in batch.tier_distribution


def test_difficulty_classification():
    """Test difficulty tier classification."""
    generator = CurriculumGenerator()

    # Easy (pass_rate >= 60%)
    assert generator._classify_difficulty("test", 0.7) == DifficultyTier.easy
    assert generator._classify_difficulty("test", 0.6) == DifficultyTier.easy

    # Medium (30% <= pass_rate < 60%)
    assert generator._classify_difficulty("test", 0.5) == DifficultyTier.medium
    assert generator._classify_difficulty("test", 0.3) == DifficultyTier.medium

    # Hard (pass_rate < 30%)
    assert generator._classify_difficulty("test", 0.2) == DifficultyTier.hard
    assert generator._classify_difficulty("test", 0.1) == DifficultyTier.hard


def test_adversarial_variants():
    """Test adversarial variant generation."""
    generator = CurriculumGenerator()

    cluster = FailureCluster(
        failure_family="routing_error",
        count=1,
        examples=[{"user_message": "test message"}],
        categories=["routing_error"],
        pass_rate=0.5,
    )

    # Generate base prompts
    base_prompts = generator._synthesize_prompts_for_cluster(cluster)
    assert len(base_prompts) > 0

    # Generate adversarial variants
    adversarial = generator._generate_adversarial_variants(cluster, base_prompts[:1])

    # Should generate 3 variants per base prompt: edge case, ambiguous, multi-intent
    assert len(adversarial) == 3

    # Check variant types
    variant_types = [p.metadata.get("variant_type") for p in adversarial]
    assert "edge_case" in variant_types
    assert "ambiguous" in variant_types
    assert "multi_intent" in variant_types

    # All should be adversarial tier
    for prompt in adversarial:
        assert prompt.tier == DifficultyTier.adversarial


def test_curriculum_store(tmp_path):
    """Test curriculum batch storage and retrieval."""
    store = CurriculumStore(store_dir=str(tmp_path))

    # Create a test batch
    generator = CurriculumGenerator(prompts_per_cluster=1, adversarial_ratio=0.0)
    cluster = FailureCluster(
        failure_family="test",
        count=1,
        examples=[{"user_message": "test"}],
        categories=["test"],
        pass_rate=0.5,
    )
    batch = generator.generate_curriculum([cluster])

    # Save batch
    filepath = store.save_batch(batch)
    assert filepath.endswith(".json")

    # Load batch
    loaded = store.load_batch(batch.batch_id)
    assert loaded is not None
    assert loaded.batch_id == batch.batch_id
    assert len(loaded.prompts) == len(batch.prompts)

    # List batches
    batches = store.list_batches()
    assert len(batches) == 1
    assert batches[0].batch_id == batch.batch_id


def test_apply_batch_to_eval_set(tmp_path):
    """Test applying curriculum batch to eval set."""
    store = CurriculumStore(store_dir=str(tmp_path / "curriculum"))
    eval_dir = tmp_path / "evals" / "cases"

    # Create and save a batch
    generator = CurriculumGenerator(prompts_per_cluster=1, adversarial_ratio=0.0)
    cluster = FailureCluster(
        failure_family="test",
        count=1,
        examples=[{"user_message": "test"}],
        categories=["test"],
        pass_rate=0.5,
    )
    batch = generator.generate_curriculum([cluster])
    store.save_batch(batch)

    # Apply to eval set
    eval_file = store.apply_batch_to_eval_set(batch.batch_id, str(eval_dir))
    assert eval_file.endswith(".yaml")
    assert (tmp_path / "evals" / "cases").exists()


def test_record_prompt_outcome():
    """Test recording prompt outcomes for pass rate tracking."""
    generator = CurriculumGenerator()

    prompt_id = "test_prompt_123"

    # Record a pass
    generator.record_prompt_outcome(prompt_id, passed=True)
    assert prompt_id in generator._pass_rate_history
    assert generator._pass_rate_history[prompt_id] == 1.0

    # Record a failure (should average)
    generator.record_prompt_outcome(prompt_id, passed=False)
    assert generator._pass_rate_history[prompt_id] < 1.0


def test_empty_clusters():
    """Test handling of empty failure clusters."""
    generator = CurriculumGenerator()

    # Generate with no clusters
    batch = generator.generate_curriculum([])

    assert batch.batch_id.startswith("curriculum_")
    assert len(batch.prompts) == 0
    assert len(batch.source_clusters) == 0


def test_curriculum_generator_assigns_unique_prompt_ids_even_for_repeated_variants():
    """Repeated synthesized prompts should still receive unique IDs within one batch."""
    generator = CurriculumGenerator(prompts_per_cluster=3, adversarial_ratio=1.0)

    cluster = FailureCluster(
        failure_family="routing_error",
        count=3,
        examples=[
            {"user_message": "route me"},
            {"user_message": "route me"},
            {"user_message": "route me"},
        ],
        categories=["routing_error"],
        pass_rate=0.5,
    )

    batch = generator.generate_curriculum([cluster])
    prompt_ids = [prompt.id for prompt in batch.prompts]

    assert len(prompt_ids) == len(set(prompt_ids))
