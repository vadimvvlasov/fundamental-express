"""Shared section contract (docs/spec/refactor-tasks.md T17,
docs/spec/refactor-architecture-spec.md Section 5).

A `Section` is one numbered block of a report ("## 1. ...", "## 2. ...").
Each asset class's `sections_{ordinary,bank,reit}.py` builds an ordered
`list[Section]` from its own metrics dataclass; a future shared renderer
(`reporting/markdown.py`/`reporting/pdf.py`, T19/T20) will render the
title/header/footer once and loop over this list for the body, instead of
each of the six current build_*_report() functions hand-assembling the
same skeleton with different field names.

Pure content contract - no knowledge of any asset class, no I/O.

`notes_markdown_block()` / `notes_flowables()` are the shared renderers
for the optional trailing analyst-notes section (cli --analyst-notes /
--analyst-notes-file): markdown `#`-headings inside the notes become real
sub-headings (demoted two levels so they nest under the section's own
`## N.` header), everything else is quoted body text; the PDF path
mirrors this with styled heading Paragraphs since ReportLab never
interprets markdown syntax.
"""

from dataclasses import dataclass
from typing import Callable, List
import re

from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Spacer

from fundamental_express.reporting.flowables import CalloutBox
from fundamental_express.reporting.theme import COLORS, FONT_BOLD, FONT_NAME, USABLE_W, pdf_safe


@dataclass(frozen=True)
class Section:
    title: str
    markdown: Callable[[], str]
    flowables: Callable[[], list]


SectionList = List[Section]


def notes_markdown_block(notes_text):
    """Render analyst notes as markdown: `#`-headings pass through as
    real headings demoted two levels (`#` -> `###`, `##` -> `####`,
    capped at `######`), all other lines are `> `-quoted body text."""
    out = []
    for line in notes_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            hashes = len(stripped) - len(stripped.lstrip("#"))
            out.append("#" * min(hashes + 2, 6) + stripped[hashes:])
        elif stripped:
            out.append(f"> {stripped}")
        else:
            out.append(">")
    return "\n".join(out)


_NOTES_BODY = dict(fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6)
_NOTES_CALLOUT = dict(fontName=FONT_NAME, fontSize=9, textColor=COLORS["body"], leading=13)


def _notes_inline(text):
    """Inline formatting for notes PDF text: `**bold**` becomes bold,
    `- ` list items become bullets. Emoji falls back to a plain circle
    via pdf_safe() (DejaVu has no color-emoji glyphs). Markdown viewers
    render the source syntax natively, so the MD path needs none of this."""
    text = pdf_safe(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    if text.startswith("- "):
        text = "• " + text[2:]
    return text


def notes_flowables(notes_text):
    """PDF mirror of notes_markdown_block(): headings become styled
    heading Paragraphs, blank lines split body text into separate
    muted CalloutBoxes, `**bold**`/`- ` lists render as rich text."""
    body_style = ParagraphStyle("NotesBody", **_NOTES_BODY)
    callout_style = ParagraphStyle("NotesCallout", **_NOTES_CALLOUT)
    items = [
        Paragraph(
            "Вывод аналитика по отчёту выше — суждение, а не расчёт методики.",
            body_style,
        )
    ]
    buf = []

    def flush():
        if buf:
            items.append(CalloutBox(
                "<br/>".join(_notes_inline(line) for line in buf),
                USABLE_W, COLORS, callout_style, COLORS["muted"],
            ))
            buf.clear()

    for line in notes_text.splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            items.append(Spacer(1, 6))
            continue
        if stripped.startswith("#"):
            flush()
            hashes = len(stripped) - len(stripped.lstrip("#"))
            size = 12 if hashes == 1 else (11 if hashes == 2 else 10)
            items.append(Paragraph(
                f"<b>{_notes_inline(stripped[hashes:].strip())}</b>",
                ParagraphStyle(
                    "NotesH", fontName=FONT_BOLD, fontSize=size,
                    textColor=COLORS["heading"], leading=size + 3,
                    spaceBefore=8, spaceAfter=4,
                ),
            ))
            continue
        buf.append(stripped)
    flush()
    return items
