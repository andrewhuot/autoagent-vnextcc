"""AutoAgent VNext agent package."""


def create_root_agent(*args, **kwargs):
    """Create the root agent. Lazy import to avoid loading google.adk at module level."""
    from agent.root_agent import create_root_agent as _create

    return _create(*args, **kwargs)


__all__ = ["create_root_agent"]
