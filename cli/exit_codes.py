"""Centralized exit codes for the AgentLab CLI.

Codes 0–9 are reserved for standard process exit semantics.
Codes 10+ are AgentLab-specific failure modes that scripts can switch on.
"""

EXIT_OK = 0
EXIT_GENERIC_ERROR = 1

EXIT_MOCK_FALLBACK = 12
"""--strict-live was set, but a step fell back to mock execution."""

EXIT_DEGRADED_DEPLOY = 13
"""Deploy was attempted on a workspace whose latest eval was degraded."""

EXIT_MISSING_PROVIDER = 14
"""Live mode requested but no provider credentials are configured."""
