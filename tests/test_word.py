import os

import pytest


@pytest.fixture(autouse=True)
def temp_workspace(tmp_path):
    from core.config import reload_config

    cfg = reload_config()
    cfg.paths.workspace_dir = str(tmp_path)
    yield tmp_path
    reload_config()


def test_create_document_produces_real_docx(temp_workspace, monkeypatch):
    from apps.word import create_document

    monkeypatch.setattr("computer.windows.open_application", lambda path: {"ok": True})

    result = create_document(
        title="Indus Valley Essay",
        output_filename="essay.docx",
        sections=[
            {"heading": "Introduction", "paragraphs": ["The Indus Valley Civilization was a Bronze Age society."]},
            {"heading": "Cities", "paragraphs": ["Harappa and Mohenjo-daro were major urban centers."]},
        ],
        open_after=True,
    )

    assert result["ok"] is True
    assert os.path.exists(result["path"])
    assert result["word_count"] > 0

    from docx import Document

    doc = Document(result["path"])
    full_text = "\n".join(p.text for p in doc.paragraphs)
    assert "Indus Valley Essay" in full_text
    assert "Harappa" in full_text


def test_create_document_without_heading_sections(temp_workspace):
    """A single flowing essay with no per-section headings should still work."""
    from apps.word import create_document

    result = create_document(
        title="Untitled",
        output_filename="flow.docx",
        sections=[{"paragraphs": ["Just one paragraph, no heading."]}],
        open_after=False,
    )
    assert result["ok"] is True
