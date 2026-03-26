"""File upload handling and processing for assistant inputs.

Supports:
- CSV/JSON/JSONL transcript files
- PDF documents
- Text files
- ZIP archives
- Audio files (MP3, WAV, M4A) - TODO: integrate Whisper transcription
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
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

    Handles various file formats and extracts conversation transcripts,
    documents, and other structured data.
    """

    SUPPORTED_TRANSCRIPT_FORMATS = {".csv", ".json", ".jsonl"}
    SUPPORTED_DOCUMENT_FORMATS = {".pdf", ".txt", ".md"}
    SUPPORTED_AUDIO_FORMATS = {".mp3", ".wav", ".m4a"}
    SUPPORTED_ARCHIVE_FORMATS = {".zip"}

    def __init__(self) -> None:
        """Initialize file processor."""
        pass

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

        file_type = file_type or path.suffix.lower()

        try:
            if file_type in self.SUPPORTED_TRANSCRIPT_FORMATS:
                return self._process_transcript_file(path, file_type)
            if file_type in self.SUPPORTED_DOCUMENT_FORMATS:
                return self._process_document_file(path, file_type)
            if file_type in self.SUPPORTED_AUDIO_FORMATS:
                return self._process_audio_file(path, file_type)
            if file_type in self.SUPPORTED_ARCHIVE_FORMATS:
                return self._process_archive_file(path)

            raise ValueError(
                f"Unsupported file type: {file_type}. "
                f"Supported: {', '.join(self.SUPPORTED_TRANSCRIPT_FORMATS | self.SUPPORTED_DOCUMENT_FORMATS | self.SUPPORTED_AUDIO_FORMATS | self.SUPPORTED_ARCHIVE_FORMATS)}"
            )
        except Exception as exc:
            return ProcessedFile(
                file_type=file_type,
                content_type="unknown",
                error=f"Error processing file: {exc}",
            )

    def _process_transcript_file(
        self, path: Path, file_type: str
    ) -> ProcessedFile:
        """Process transcript files (CSV, JSON, JSONL).

        Expected formats:
        - CSV: columns like user_message, assistant_message, specialist_used, etc.
        - JSON: array of conversation objects
        - JSONL: one conversation object per line
        """
        records: list[dict[str, Any]] = []

        if file_type == ".csv":
            with path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                records = list(reader)

        elif file_type == ".json":
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    records = data
                elif isinstance(data, dict):
                    records = [data]
                else:
                    raise ValueError("JSON must be array or object")

        elif file_type == ".jsonl":
            with path.open("r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        raise ValueError(f"Invalid JSON on line {line_num}: {e}") from e

        # Normalize conversation records
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
            # Try different field name variations
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
        """Process document files (PDF, TXT, MD).

        Extracts text content from documents for knowledge extraction.
        """
        text_content = ""

        if file_type == ".txt" or file_type == ".md":
            with path.open("r", encoding="utf-8") as f:
                text_content = f.read()

        elif file_type == ".pdf":
            text_content = self._extract_pdf_text(path)

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

    def _extract_pdf_text(self, path: Path) -> str:
        """Extract text from PDF file.

        TODO: Integrate a PDF parsing library (PyPDF2, pdfplumber, etc.)
        For now, returns a placeholder.
        """
        # Placeholder implementation
        # In production, use:
        # import pdfplumber
        # with pdfplumber.open(path) as pdf:
        #     text = "\n".join(page.extract_text() for page in pdf.pages)
        # return text

        return f"[PDF text extraction not yet implemented for {path.name}]\n\nTODO: Install pdfplumber or PyPDF2 and implement PDF text extraction."

    def _process_audio_file(
        self, path: Path, file_type: str
    ) -> ProcessedFile:
        """Process audio files (MP3, WAV, M4A).

        TODO: Integrate Whisper API for transcription.
        For now, returns a placeholder.
        """
        # Placeholder implementation
        # In production, use:
        # import openai
        # with open(path, 'rb') as f:
        #     transcript = openai.Audio.transcribe("whisper-1", f)
        # return ProcessedFile(
        #     file_type=file_type,
        #     content_type="transcripts",
        #     text_content=transcript['text'],
        #     metadata={"source_file": path.name}
        # )

        return ProcessedFile(
            file_type=file_type,
            content_type="audio",
            text_content=f"[Audio transcription not yet implemented for {path.name}]",
            metadata={
                "source_file": path.name,
                "file_size_bytes": path.stat().st_size,
            },
            error="Audio transcription requires Whisper API integration (TODO)",
        )

    def _process_archive_file(self, path: Path) -> ProcessedFile:
        """Process archive files (ZIP).

        Extracts and processes all supported files within the archive.
        """
        records: list[dict[str, Any]] = []
        text_content_parts: list[str] = []
        file_count = 0

        try:
            with zipfile.ZipFile(path, "r") as zf:
                for member in zf.namelist():
                    if member.endswith("/"):
                        continue  # Skip directories

                    member_path = Path(member)
                    suffix = member_path.suffix.lower()

                    if suffix not in (
                        self.SUPPORTED_TRANSCRIPT_FORMATS
                        | self.SUPPORTED_DOCUMENT_FORMATS
                    ):
                        continue

                    file_count += 1

                    # Extract to temporary bytes buffer
                    with zf.open(member) as member_file:
                        content_bytes = member_file.read()

                    # Process based on file type
                    if suffix in self.SUPPORTED_TRANSCRIPT_FORMATS:
                        # Create temporary file-like object
                        temp_file = io.StringIO(content_bytes.decode("utf-8"))
                        if suffix == ".csv":
                            reader = csv.DictReader(temp_file)
                            records.extend(list(reader))
                        elif suffix == ".json":
                            temp_file.seek(0)
                            data = json.load(temp_file)
                            if isinstance(data, list):
                                records.extend(data)
                            else:
                                records.append(data)
                        elif suffix == ".jsonl":
                            temp_file.seek(0)
                            for line in temp_file:
                                line = line.strip()
                                if line:
                                    records.append(json.loads(line))

                    elif suffix in {".txt", ".md"}:
                        text_content_parts.append(
                            content_bytes.decode("utf-8", errors="ignore")
                        )

        except zipfile.BadZipFile as e:
            return ProcessedFile(
                file_type=".zip",
                content_type="archive",
                error=f"Invalid ZIP file: {e}",
            )

        # Normalize transcript records if any
        if records:
            records = self._normalize_transcript_records(records)

        return ProcessedFile(
            file_type=".zip",
            content_type="transcripts" if records else "documents",
            records=records,
            text_content="\n\n".join(text_content_parts),
            metadata={
                "source_file": path.name,
                "extracted_files": file_count,
                "record_count": len(records),
                "total_text_chars": sum(len(t) for t in text_content_parts),
            },
        )

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
