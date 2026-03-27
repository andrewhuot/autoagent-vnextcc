"""File upload handling and processing for assistant inputs.

Supports:
- CSV/JSON/JSONL transcript files
- PDF/TXT/MD/DOCX documents
- Whiteboard / image uploads (best-effort interpretation)
- ZIP archives containing mixed modalities
- Audio files (MP3, WAV, M4A) with sidecar transcript fallback
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from html import unescape
from pathlib import Path
from typing import Any


@dataclass
class ProcessedFile:
    """Result of processing an uploaded file."""

    file_type: str
    content_type: str  # "transcripts", "documents", "audio", "config"
    records: list[dict[str, Any]] = field(default_factory=list)
    text_content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class FileProcessor:
    """Process uploaded files into structured data for assistant operations.

    WHY: Assistant workflows should accept real-world CX inputs (transcripts,
    playbooks, whiteboards, audio notes) without forcing manual pre-cleaning.
    """

    SUPPORTED_TRANSCRIPT_FORMATS = {".csv", ".json", ".jsonl"}
    SUPPORTED_DOCUMENT_FORMATS = {".pdf", ".txt", ".md", ".docx"}
    SUPPORTED_IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".webp"}
    SUPPORTED_AUDIO_FORMATS = {".mp3", ".wav", ".m4a"}
    SUPPORTED_ARCHIVE_FORMATS = {".zip"}

    def __init__(self) -> None:
        """Initialize file processor."""

    def process_file(
        self, file_path: str | Path, file_type: str | None = None
    ) -> ProcessedFile:
        """Process a file and extract structured data.

        Args:
            file_path: Path to the file to process
            file_type: Optional explicit file type (auto-detected from extension if None)

        Returns:
            ProcessedFile with extracted data

        Raises:
            ValueError: If file format is unsupported
            FileNotFoundError: If file does not exist
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        file_type = (file_type or path.suffix).lower()

        try:
            if file_type in self.SUPPORTED_TRANSCRIPT_FORMATS:
                return self._process_transcript_file(path, file_type)
            if file_type in self.SUPPORTED_DOCUMENT_FORMATS:
                return self._process_document_file(path, file_type)
            if file_type in self.SUPPORTED_IMAGE_FORMATS:
                return self._process_image_file(path, file_type)
            if file_type in self.SUPPORTED_AUDIO_FORMATS:
                return self._process_audio_file(path, file_type)
            if file_type in self.SUPPORTED_ARCHIVE_FORMATS:
                return self._process_archive_file(path)

            raise ValueError(
                f"Unsupported file type: {file_type}. "
                f"Supported: {', '.join(self._all_supported_formats())}"
            )
        except Exception as exc:
            return ProcessedFile(
                file_type=file_type,
                content_type="unknown",
                error=f"Error processing file: {exc}",
            )

    def _all_supported_formats(self) -> list[str]:
        formats = (
            self.SUPPORTED_TRANSCRIPT_FORMATS
            | self.SUPPORTED_DOCUMENT_FORMATS
            | self.SUPPORTED_IMAGE_FORMATS
            | self.SUPPORTED_AUDIO_FORMATS
            | self.SUPPORTED_ARCHIVE_FORMATS
        )
        return sorted(formats)

    def _process_transcript_file(
        self, path: Path, file_type: str
    ) -> ProcessedFile:
        """Process transcript files (CSV, JSON, JSONL)."""
        content_bytes = path.read_bytes()
        records = self._parse_transcript_bytes(content_bytes, file_type)
        normalized = self._normalize_transcript_records(records)

        return ProcessedFile(
            file_type=file_type,
            content_type="transcripts",
            records=normalized,
            metadata={
                "record_count": len(normalized),
                "source_file": path.name,
            },
        )

    def _parse_transcript_bytes(
        self,
        content_bytes: bytes,
        file_type: str,
    ) -> list[dict[str, Any]]:
        """Parse transcript bytes into raw records."""
        records: list[dict[str, Any]] = []
        text = content_bytes.decode("utf-8", errors="ignore")

        if file_type == ".csv":
            reader = csv.DictReader(io.StringIO(text))
            records = list(reader)

        elif file_type == ".json":
            data = json.loads(text)
            if isinstance(data, list):
                records = data
            elif isinstance(data, dict):
                records = [data]
            else:
                raise ValueError("JSON must be array or object")

        elif file_type == ".jsonl":
            for line_num, line in enumerate(text.splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON on line {line_num}: {exc}") from exc

        return records

    def _normalize_transcript_records(
        self, records: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Normalize transcript records to a standard format.

        Standard format:
        {
            "conversation_id": str,
            "user_message": str,
            "assistant_message": str,
            "specialist_used": str (optional),
            "success": bool (optional),
            "metadata": dict (optional)
        }
        """
        normalized = []

        for i, record in enumerate(records):
            user_msg = (
                record.get("user_message")
                or record.get("user")
                or record.get("input")
                or record.get("prompt")
                or ""
            )
            assistant_msg = (
                record.get("assistant_message")
                or record.get("assistant")
                or record.get("response")
                or record.get("output")
                or ""
            )

            normalized_record = {
                "conversation_id": record.get("conversation_id")
                or record.get("id")
                or f"conv_{i:05d}",
                "user_message": str(user_msg),
                "assistant_message": str(assistant_msg),
                "specialist_used": record.get("specialist_used")
                or record.get("specialist"),
                "success": record.get("success"),
                "metadata": {
                    k: v
                    for k, v in record.items()
                    if k
                    not in {
                        "conversation_id",
                        "id",
                        "user_message",
                        "user",
                        "input",
                        "prompt",
                        "assistant_message",
                        "assistant",
                        "response",
                        "output",
                        "specialist_used",
                        "specialist",
                        "success",
                    }
                },
            }
            normalized.append(normalized_record)

        return normalized

    def _process_document_file(
        self, path: Path, file_type: str
    ) -> ProcessedFile:
        """Process document files (PDF, TXT, MD, DOCX)."""
        content_bytes = path.read_bytes()
        text_content = self._extract_document_text_from_bytes(
            content_bytes=content_bytes,
            file_type=file_type,
            source_name=path.name,
        )

        return ProcessedFile(
            file_type=file_type,
            content_type="documents",
            text_content=text_content,
            metadata={
                "char_count": len(text_content),
                "word_count": len(text_content.split()),
                "source_file": path.name,
            },
        )

    def _extract_document_text_from_bytes(
        self,
        content_bytes: bytes,
        file_type: str,
        source_name: str,
    ) -> str:
        """Extract text from a document payload."""
        if file_type in {".txt", ".md"}:
            return content_bytes.decode("utf-8", errors="ignore")
        if file_type == ".pdf":
            return self._extract_pdf_text_from_bytes(content_bytes, source_name)
        if file_type == ".docx":
            return self._extract_docx_text_from_bytes(content_bytes, source_name)
        return ""

    def _extract_pdf_text(self, path: Path) -> str:
        """Extract text from PDF file.

        WHY: Preserve compatibility for callsites that still pass filesystem paths.
        """
        return self._extract_pdf_text_from_bytes(path.read_bytes(), path.name)

    def _extract_pdf_text_from_bytes(self, content_bytes: bytes, source_name: str) -> str:
        """Extract text from PDF bytes with optional parser fallback."""
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(io.BytesIO(content_bytes))
            pages = [page.extract_text() or "" for page in reader.pages]
            text = "\n".join(page.strip() for page in pages if page and page.strip())
            if text:
                return text
        except Exception:
            pass

        decoded = content_bytes.decode("utf-8", errors="ignore")
        if decoded.strip():
            return decoded
        return f"[PDF text extraction unavailable for {source_name}]"

    def _extract_docx_text_from_bytes(self, content_bytes: bytes, source_name: str) -> str:
        """Extract text from a DOCX payload using internal XML content."""
        try:
            with zipfile.ZipFile(io.BytesIO(content_bytes), "r") as archive:
                xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
        except Exception:
            return f"[DOCX extraction unavailable for {source_name}]"

        # Extract all text nodes and normalize whitespace.
        chunks = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, flags=re.DOTALL)
        text = " ".join(unescape(chunk).strip() for chunk in chunks if chunk.strip())
        return re.sub(r"\s+", " ", text).strip() or f"[DOCX appears empty: {source_name}]"

    def _process_image_file(
        self, path: Path, file_type: str
    ) -> ProcessedFile:
        """Interpret uploaded whiteboard/image inputs as workflow hints.

        WHY: Ghostwriter-like workflows ingest screenshots/photos that often embed
        process steps and escalation logic. We preserve those hints as text.
        """
        content_bytes = path.read_bytes()
        text_content = self._interpret_visual_bytes(content_bytes, source_name=path.name)

        return ProcessedFile(
            file_type=file_type,
            content_type="documents",
            text_content=text_content,
            metadata={
                "source_file": path.name,
                "modality": "whiteboard_image",
                "char_count": len(text_content),
            },
        )

    def _interpret_visual_bytes(self, content_bytes: bytes, source_name: str) -> str:
        """Best-effort visual interpretation without external OCR dependency."""
        decoded = content_bytes.decode("utf-8", errors="ignore")
        lines = [line.strip() for line in decoded.splitlines() if line.strip()]

        workflow_lines = [
            line
            for line in lines
            if any(token in line.lower() for token in ["step", "->", "workflow", "escalate", "verify", "lookup"])
        ]
        if workflow_lines:
            return "\n".join(workflow_lines)

        if decoded.strip():
            return decoded.strip()

        return (
            f"[Visual workflow uploaded: {source_name}]\n"
            "No OCR text available. Treat this artifact as a whiteboard sketch and request a brief caption."
        )

    def _process_audio_file(
        self, path: Path, file_type: str
    ) -> ProcessedFile:
        """Process audio files (MP3, WAV, M4A).

        WHY: In competitive workflows, audio uploads should still be usable even
        without external ASR services by honoring sidecar transcripts and fallbacks.
        """
        transcript, mode = self._extract_audio_sidecar_text(path)

        if not transcript:
            transcript = (
                f"Audio note from {path.stem.replace('_', ' ')}. "
                "No transcript file was found; include a sidecar .txt for higher-fidelity ingestion."
            )
            mode = "filename_heuristic"

        return ProcessedFile(
            file_type=file_type,
            content_type="transcripts",
            text_content=transcript,
            metadata={
                "source_file": path.name,
                "file_size_bytes": path.stat().st_size,
                "transcription_mode": mode,
            },
            error=None,
        )

    def _extract_audio_sidecar_text(self, path: Path) -> tuple[str, str]:
        """Extract transcript text from sidecar files located next to audio."""
        for sidecar_suffix in (".txt", ".md", ".json"):
            sidecar = path.with_suffix(sidecar_suffix)
            if not sidecar.exists():
                continue

            content = sidecar.read_text(encoding="utf-8", errors="ignore").strip()
            if not content:
                continue

            if sidecar_suffix == ".json":
                try:
                    payload = json.loads(content)
                    if isinstance(payload, dict):
                        content = str(payload.get("transcript") or payload.get("text") or "").strip()
                    elif isinstance(payload, list):
                        content = "\n".join(str(item) for item in payload if str(item).strip())
                except json.JSONDecodeError:
                    # Keep raw text if JSON parsing fails.
                    pass

            if content:
                return content, f"sidecar:{sidecar.name}"

        return "", "none"

    def _process_archive_file(self, path: Path) -> ProcessedFile:
        """Process archive files (ZIP).

        Extracts and processes all supported files within the archive.
        """
        records: list[dict[str, Any]] = []
        text_content_parts: list[str] = []
        file_count = 0

        try:
            with zipfile.ZipFile(path, "r") as zf:
                members = {
                    name: zf.read(name)
                    for name in zf.namelist()
                    if not name.endswith("/")
                }
        except zipfile.BadZipFile as exc:
            return ProcessedFile(
                file_type=".zip",
                content_type="archive",
                error=f"Invalid ZIP file: {exc}",
            )

        for member_name, content_bytes in members.items():
            member_path = Path(member_name)
            suffix = member_path.suffix.lower()

            if suffix in self.SUPPORTED_TRANSCRIPT_FORMATS:
                records.extend(self._parse_transcript_bytes(content_bytes, suffix))
                file_count += 1
                continue

            if suffix in self.SUPPORTED_DOCUMENT_FORMATS:
                text_content_parts.append(
                    self._extract_document_text_from_bytes(
                        content_bytes=content_bytes,
                        file_type=suffix,
                        source_name=member_path.name,
                    )
                )
                file_count += 1
                continue

            if suffix in self.SUPPORTED_IMAGE_FORMATS:
                text_content_parts.append(
                    self._interpret_visual_bytes(content_bytes, source_name=member_path.name)
                )
                file_count += 1
                continue

            if suffix in self.SUPPORTED_AUDIO_FORMATS:
                sidecar_text = self._extract_audio_sidecar_from_archive(member_path, members)
                if sidecar_text:
                    text_content_parts.append(sidecar_text)
                else:
                    text_content_parts.append(
                        f"Audio note from {member_path.stem.replace('_', ' ')} (no transcript sidecar found)."
                    )
                file_count += 1
                continue

        if records:
            records = self._normalize_transcript_records(records)

        return ProcessedFile(
            file_type=".zip",
            content_type="transcripts" if records else "documents",
            records=records,
            text_content="\n\n".join(part for part in text_content_parts if part.strip()),
            metadata={
                "source_file": path.name,
                "extracted_files": file_count,
                "record_count": len(records),
                "total_text_chars": sum(len(t) for t in text_content_parts),
            },
        )

    def _extract_audio_sidecar_from_archive(
        self,
        member_path: Path,
        members: dict[str, bytes],
    ) -> str:
        """Look for sidecar transcript files for archive audio members."""
        candidates = [
            member_path.with_suffix(".txt"),
            member_path.with_suffix(".md"),
            member_path.with_suffix(".json"),
        ]

        for candidate in candidates:
            raw = members.get(candidate.as_posix())
            if raw is None:
                # Windows-generated ZIPs can include backslashes in names.
                raw = members.get(str(candidate))
            if raw is None:
                continue

            text = raw.decode("utf-8", errors="ignore").strip()
            if not text:
                continue

            if candidate.suffix.lower() == ".json":
                try:
                    payload = json.loads(text)
                    if isinstance(payload, dict):
                        text = str(payload.get("transcript") or payload.get("text") or "").strip()
                except json.JSONDecodeError:
                    pass

            if text:
                return text

        return ""

    @staticmethod
    def validate_transcript_records(
        records: list[dict[str, Any]]
    ) -> tuple[bool, str]:
        """Validate that transcript records have required fields.

        Args:
            records: List of transcript records to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not records:
            return False, "No transcript records found"

        required_fields = {"user_message"}
        for i, record in enumerate(records):
            missing = required_fields - set(record.keys())
            if missing:
                return (
                    False,
                    f"Record {i} missing required fields: {', '.join(missing)}",
                )

            if not record.get("user_message"):
                return False, f"Record {i} has empty user_message"

        return True, ""

    @staticmethod
    def extract_metadata_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
        """Extract summary statistics from transcript records.

        Args:
            records: List of transcript records

        Returns:
            Summary dictionary with counts, unique specialists, etc.
        """
        if not records:
            return {"record_count": 0}

        specialists = {r.get("specialist_used") for r in records if r.get("specialist_used")}
        success_count = sum(1 for r in records if r.get("success") is True)
        failure_count = sum(1 for r in records if r.get("success") is False)

        total_user_chars = sum(len(r.get("user_message", "")) for r in records)
        total_assistant_chars = sum(len(r.get("assistant_message", "")) for r in records)

        return {
            "record_count": len(records),
            "unique_specialists": len(specialists),
            "specialists": sorted(specialists),
            "success_count": success_count,
            "failure_count": failure_count,
            "unknown_success_count": len(records) - success_count - failure_count,
            "avg_user_message_chars": total_user_chars // len(records) if records else 0,
            "avg_assistant_message_chars": total_assistant_chars // len(records) if records else 0,
        }
