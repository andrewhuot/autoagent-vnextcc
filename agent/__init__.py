"""AutoAgent VNext agent package."""


def create_root_agent(*args, **kwargs):
    """Create the root agent. Lazy import to avoid loading google.adk at module level."""
    from agent.root_agent import create_root_agent as _create

    return _create(*args, **kwargs)


def create_eval_agent(*args, **kwargs):
    """Create the eval-compatible agent adapter lazily to avoid heavy imports on module load."""
    from agent.eval_agent import create_eval_agent as _create

    return _create(*args, **kwargs)


__all__ = ["create_root_agent", "create_eval_agent"]
