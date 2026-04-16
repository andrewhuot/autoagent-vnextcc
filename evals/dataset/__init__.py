"""Thin dataset utilities for eval corpora.

Free functions only — no Dataset class. See plan §1.2.
"""

from .importers import load_csv, load_jsonl

__all__ = ["load_csv", "load_jsonl"]
