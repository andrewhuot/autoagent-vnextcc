"""Tests for assistant.file_processor multimodal ingestion paths."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from assistant.file_processor import FileProcessor


def _write_docx(path: Path, text: str) -> None:
    """Write a minimal DOCX archive with the provided text."""
    document_xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
        "<w:body><w:p><w:r><w:t>"
        f"{text}"
        "</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types></Types>")
        archive.writestr("word/document.xml", document_xml)


def test_process_docx_extracts_document_text(tmp_path: Path) -> None:
    processor = FileProcessor()
    docx_path = tmp_path / "sop.docx"
    _write_docx(docx_path, "Escalate only after identity verification.")

    result = processor.process_file(docx_path)

    assert result.error is None
    assert result.content_type == "documents"
    assert "identity verification" in result.text_content.lower()


def test_process_audio_uses_sidecar_transcript_when_present(tmp_path: Path) -> None:
    processor = FileProcessor()
    audio_path = tmp_path / "call.mp3"
    sidecar_path = tmp_path / "call.txt"

    audio_path.write_bytes(b"not-real-audio")
    sidecar_path.write_text(
        "Customer: I do not have my order number.\nAgent: I will verify identity first.",
        encoding="utf-8",
    )

    result = processor.process_file(audio_path)

    assert result.error is None
    assert result.content_type == "transcripts"
    assert "verify identity" in result.text_content.lower()


def test_process_whiteboard_image_extracts_workflow_hints(tmp_path: Path) -> None:
    processor = FileProcessor()
    image_path = tmp_path / "whiteboard.png"
    image_path.write_bytes(
        b"Step 1: verify order id\nStep 2: fallback lookup\nStep 3: escalate with context"
    )

    result = processor.process_file(image_path)

    assert result.error is None
    assert result.content_type == "documents"
    assert "step 1" in result.text_content.lower()
    assert "fallback lookup" in result.text_content.lower()


def test_process_archive_includes_multimodal_content(tmp_path: Path) -> None:
    processor = FileProcessor()
    archive_path = tmp_path / "bundle.zip"

    transcripts = [
        {
            "conversation_id": "conv-1",
            "user_message": "Where is my order?",
            "assistant_message": "Let me check your tracking status.",
        }
    ]

    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("transcripts.json", json.dumps(transcripts))
        archive.writestr("playbook.txt", "Step 1: Verify customer. Step 2: Check order status.")
        archive.writestr("whiteboard.jpg", "Step 1 -> Step 2 -> Escalate")
        archive.writestr("voice_note.wav", b"fake-audio")
        archive.writestr("voice_note.txt", "Customer asked for refund without order number.")

    result = processor.process_file(archive_path)

    assert result.error is None
    assert result.content_type in {"transcripts", "documents"}
    assert len(result.records) >= 1
    text_blob = result.text_content.lower()
    assert "verify customer" in text_blob
    assert "refund without order number" in text_blob
    assert result.metadata.get("extracted_files", 0) >= 4
