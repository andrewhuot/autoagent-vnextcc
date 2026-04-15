"""Concrete :class:`~cli.llm.types.ModelClient` implementations.

Each provider adapter lives in its own module with a lazy SDK import so
agentlab loads cleanly on systems without the optional dependencies. The
factory in :mod:`cli.llm.providers.factory` picks a concrete client
based on the active model name plus env/config credentials.
"""

from __future__ import annotations

from cli.llm.providers.factory import (
    MODEL_PROVIDERS,
    ProviderFactoryError,
    create_model_client,
    resolve_provider,
)

__all__ = [
    "MODEL_PROVIDERS",
    "ProviderFactoryError",
    "create_model_client",
    "resolve_provider",
]
