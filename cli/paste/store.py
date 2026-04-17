"""Content-addressed storage for large pasted text."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


_INDEX_FILE = "index.json"


@dataclass(frozen=True)
class PasteHandle:
    """Stable metadata for one stored paste."""

    id: str
    line_count: int
    preview: str
    display_number: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class PasteStore:
    """Persist paste contents under a content-addressed root."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._index_path = self._root / _INDEX_FILE
        self._hash_to_number: dict[str, int] = {}
        self._number_to_hash: dict[int, str] = {}
        self._load_index()

    def store(self, text: str) -> PasteHandle:
        paste_id = hashlib.sha256(text.encode("utf-8")).hexdigest()
        path = self._root / f"{paste_id}.txt"
        if not path.exists():
            path.write_text(text, encoding="utf-8")

        display_number = self._hash_to_number.get(paste_id)
        if display_number is None:
            display_number = max(self._number_to_hash.keys(), default=0) + 1
            self._hash_to_number[paste_id] = display_number
            self._number_to_hash[display_number] = paste_id
            self._write_index()

        lines = text.splitlines()
        preview = lines[0] if lines else ""
        return PasteHandle(
            id=paste_id,
            line_count=max(len(lines), 1 if text else 0),
            preview=preview,
            display_number=display_number,
        )

    def load(self, paste_id: str) -> str:
        return (self._root / f"{paste_id}.txt").read_text(encoding="utf-8")

    def load_by_display_number(self, display_number: int) -> str:
        paste_id = self._number_to_hash[display_number]
        return self.load(paste_id)

    def _load_index(self) -> None:
        if not self._index_path.exists():
            return
        payload = json.loads(self._index_path.read_text(encoding="utf-8"))
        self._hash_to_number = {
            str(paste_id): int(number)
            for paste_id, number in payload.get("hash_to_number", {}).items()
        }
        self._number_to_hash = {
            int(number): str(paste_id)
            for number, paste_id in payload.get("number_to_hash", {}).items()
        }

    def _write_index(self) -> None:
        self._index_path.write_text(
            json.dumps(
                {
                    "hash_to_number": self._hash_to_number,
                    "number_to_hash": self._number_to_hash,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
