"""Static analysis for skill packages — safety checks before installation."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class StaticAnalysisResult:
    safe: bool
    warnings: list[str]
    blocked_imports: list[str]
    suspicious_patterns: list[str]

    def to_dict(self) -> dict:
        return {
            "safe": self.safe,
            "warnings": self.warnings,
            "blocked_imports": self.blocked_imports,
            "suspicious_patterns": self.suspicious_patterns,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StaticAnalysisResult":
        return cls(
            safe=d.get("safe", True),
            warnings=d.get("warnings", []),
            blocked_imports=d.get("blocked_imports", []),
            suspicious_patterns=d.get("suspicious_patterns", []),
        )


# ---------------------------------------------------------------------------
# Blocked / risky sets
# ---------------------------------------------------------------------------

_BLOCKED_IMPORTS: set[str] = {
    "subprocess",
    "os.system",
    "pty",
    "pexpect",
    "ctypes",
    "cffi",
    "pickle",
    "shelve",
    "marshal",
    "importlib",
    "builtins",
    "__import__",
}

_RISKY_IMPORTS: set[str] = {
    "socket",
    "requests",
    "httpx",
    "urllib",
    "ftplib",
    "smtplib",
    "paramiko",
    "fabric",
}

_SUSPICIOUS_PATTERNS: list[tuple[str, str]] = [
    (r"\beval\s*\(", "use of eval()"),
    (r"\bexec\s*\(", "use of exec()"),
    (r"\bcompile\s*\(", "use of compile()"),
    (r"os\.system\s*\(", "direct shell execution via os.system()"),
    (r"os\.popen\s*\(", "shell execution via os.popen()"),
    (r"subprocess\.", "subprocess usage"),
    (r"__import__\s*\(", "dynamic import via __import__()"),
    (r"open\s*\(.*['\"]w['\"]", "file write detected"),
    (r"shutil\.(rmtree|move|copy)", "filesystem manipulation"),
    (r"base64\.b64decode", "base64 decoding (possible obfuscation)"),
]

_NETWORK_PATTERNS: list[tuple[str, str]] = [
    (r"socket\.connect\s*\(", "raw socket connection"),
    (r"requests\.(get|post|put|delete|patch)\s*\(", "HTTP request"),
    (r"httpx\.", "HTTP request via httpx"),
    (r"urllib\.request", "urllib HTTP request"),
    (r"ftplib\.", "FTP access"),
    (r"smtplib\.", "SMTP/email access"),
]


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class SkillStaticAnalyzer:
    """Performs static analysis on skill source code."""

    def analyze(self, skill_content: str) -> StaticAnalysisResult:
        """Run all checks and return a consolidated result."""
        blocked = self._check_imports(skill_content)
        suspicious = self._check_patterns(skill_content)
        network = self._check_network_access(skill_content)

        warnings: list[str] = []

        # Network access is a warning, not a block
        if network:
            for n in network:
                warnings.append(f"Network access: {n}")

        # Risky (non-blocked) imports are warnings
        risky = self._check_risky_imports(skill_content)
        for r in risky:
            warnings.append(f"Risky import: {r}")

        safe = len(blocked) == 0 and len(suspicious) == 0

        return StaticAnalysisResult(
            safe=safe,
            warnings=warnings,
            blocked_imports=blocked,
            suspicious_patterns=suspicious,
        )

    def _check_imports(self, content: str) -> list[str]:
        """Return list of blocked imports found in content."""
        found: list[str] = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in _BLOCKED_IMPORTS or alias.name.split(".")[0] in _BLOCKED_IMPORTS:
                            found.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module in _BLOCKED_IMPORTS or module.split(".")[0] in _BLOCKED_IMPORTS:
                        found.append(module)
        except SyntaxError:
            # Fall back to regex if AST parsing fails
            for imp in _BLOCKED_IMPORTS:
                if re.search(rf"\bimport\s+{re.escape(imp)}\b", content):
                    found.append(imp)
        return list(set(found))

    def _check_risky_imports(self, content: str) -> list[str]:
        """Return list of risky (but not fully blocked) imports found."""
        found: list[str] = []
        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        if root in _RISKY_IMPORTS:
                            found.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    root = module.split(".")[0]
                    if root in _RISKY_IMPORTS:
                        found.append(module)
        except SyntaxError:
            for imp in _RISKY_IMPORTS:
                if re.search(rf"\bimport\s+{re.escape(imp)}\b", content):
                    found.append(imp)
        return list(set(found))

    def _check_patterns(self, content: str) -> list[str]:
        """Return list of suspicious pattern descriptions found in content."""
        found: list[str] = []
        for pattern, description in _SUSPICIOUS_PATTERNS:
            if re.search(pattern, content):
                found.append(description)
        return found

    def _check_network_access(self, content: str) -> list[str]:
        """Return list of network-access pattern descriptions found in content."""
        found: list[str] = []
        for pattern, description in _NETWORK_PATTERNS:
            if re.search(pattern, content):
                found.append(description)
        return found
