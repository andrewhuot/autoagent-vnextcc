"""Textual-based TUI for the AgentLab workbench.

Activated when ``AGENTLAB_TUI=1`` is set. The TUI replaces the legacy
``input()`` REPL loop with a reactive widget tree driven by a centralized
:class:`~cli.workbench_app.store.Store`.
"""
