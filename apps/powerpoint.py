"""
PowerPoint automation (spec section 10) — the flagship demo feature.

Design decision: build the .pptx directly with python-pptx rather than
driving the PowerPoint UI via mouse/keyboard/UIA. This is deliberate,
not a shortcut:
  - It's deterministic — no risk of a click landing on the wrong menu
    because a dialog was slower to open than expected.
    it works even if PowerPoint isn't installed at all (you can still
    hand the .pptx to someone who has it, or open it in LibreOffice).
  - It's far faster: one Python call vs. dozens of UI actions.
UI automation is still the right tool for *editing an existing,
already-open* presentation interactively — that path (open_application
+ find_ui_element + click) still works and is used for step 6/12 of
the spec's own PowerPoint workflow (open PowerPoint, review). This
module only replaces the "author the content" steps (2-11).

The LLM is responsible for the actual content (title/bullets per
slide) — this tool's job is turning structured content into a
consistently formatted, real .pptx file, then optionally opening it
so the user can see the result (step 12 of the spec workflow).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.config import get_config
from core.logging_setup import get_logger
from core.tool_registry import registry

log = get_logger()

# A small, consistent design system so every deck looks intentional
# rather than like raw default-template output (spec section 10:
# "apply consistent formatting").
_TITLE_FONT_SIZE = 40
_HEADING_FONT_SIZE = 30
_BODY_FONT_SIZE = 18
_ACCENT_RGB = (0x1F, 0x4E, 0x79)  # a muted dark blue


def _resolve_output_path(filename: str) -> Path:
    if not filename.lower().endswith(".pptx"):
        filename += ".pptx"
    p = Path(filename).expanduser()
    if not p.is_absolute():
        p = get_config().resolved_workspace_dir() / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@registry.register(
    "create_presentation",
    (
        "Create a fully-formatted PowerPoint (.pptx) file from a title and a list of slides. "
        "Each slide has a title and a list of bullet-point strings. Generate the actual "
        "content (research the topic first if needed) before calling this tool — this tool "
        "only lays the content out and saves the file, it does not invent content."
    ),
    {
        "title": {"type": "string", "description": "Presentation title, shown on the title slide."},
        "subtitle": {"type": "string", "description": "Optional subtitle for the title slide."},
        "output_filename": {"type": "string", "description": "Filename to save as, e.g. 'Indus_Valley.pptx'."},
        "slides": {
            "type": "array",
            "description": "Content slides, in order.",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "open_after": {"type": "boolean", "description": "Open the file in PowerPoint after saving. Default true."},
    },
    required=["title", "output_filename", "slides"],
)
def create_presentation(
    title: str,
    output_filename: str,
    slides: list[dict],
    subtitle: str = "",
    open_after: bool = True,
) -> dict:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Pt

    prs = Presentation()

    # --- Title slide ---
    title_layout = prs.slide_layouts[0]
    slide = prs.slides.add_slide(title_layout)
    slide.shapes.title.text = title
    slide.shapes.title.text_frame.paragraphs[0].font.size = Pt(_TITLE_FONT_SIZE)
    slide.shapes.title.text_frame.paragraphs[0].font.color.rgb = RGBColor(*_ACCENT_RGB)
    if subtitle and len(slide.placeholders) > 1:
        slide.placeholders[1].text = subtitle

    # --- Content slides ---
    content_layout = prs.slide_layouts[1]  # "Title and Content"
    for slide_data in slides:
        heading = slide_data.get("heading", "")
        bullets = slide_data.get("bullets", [])

        s = prs.slides.add_slide(content_layout)
        s.shapes.title.text = heading
        s.shapes.title.text_frame.paragraphs[0].font.size = Pt(_HEADING_FONT_SIZE)
        s.shapes.title.text_frame.paragraphs[0].font.color.rgb = RGBColor(*_ACCENT_RGB)

        body = s.placeholders[1].text_frame
        body.clear()
        for i, bullet in enumerate(bullets):
            p = body.paragraphs[0] if i == 0 else body.add_paragraph()
            p.text = str(bullet)
            p.font.size = Pt(_BODY_FONT_SIZE)
            p.level = 0

    output_path = _resolve_output_path(output_filename)
    prs.save(str(output_path))
    log.info(f"Saved presentation: {output_path} ({len(slides)} content slides)")

    result = {"ok": True, "path": str(output_path), "slide_count": len(slides) + 1}

    if open_after:
        from computer.windows import open_application

        open_result = open_application(str(output_path))
        result["opened"] = open_result.get("ok", False)

    return result
