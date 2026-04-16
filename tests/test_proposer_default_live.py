"""R1.5: Optimizer must not silently default the Proposer to mock mode.

Background: optimizer/loop.py:118 historically forced Proposer(use_mock=True)
when no proposer was passed in. This made every default-constructed Optimizer
silently use canned proposals. R1.5 removes that override; the Proposer's own
default (use_mock=False) takes effect.
"""

from optimizer.proposer import Proposer


def test_proposer_defaults_to_live():
    """Sanity check: Proposer's own default is live."""
    p = Proposer()
    assert p.use_mock is False, (
        "Proposer should default to live; mock must be explicit opt-in."
    )


def test_optimizer_does_not_force_mock_proposer():
    """The optimizer must not override the Proposer default to mock mode."""
    # Construct Optimizer with the minimum required args (eval_runner is required).
    # We import lazily because Optimizer pulls in heavy modules.
    from optimizer.loop import Optimizer
    from evals.runner import EvalRunner

    eval_runner = EvalRunner()
    opt = Optimizer(eval_runner=eval_runner)
    assert opt.proposer.use_mock is False, (
        "Optimizer(eval_runner=...) must not silently force the proposer into mock mode. "
        "Construct with Proposer(use_mock=True) explicitly when mock is desired."
    )
