"""Analyst-notes trailing section tests.

Covers the optional analyst-notes section (cli --analyst-notes /
--analyst-notes-file): resolver contract (mutual exclusion, missing file,
None means "no section") and rendering in all three asset-class section
builders. Network-free, same fixture pattern as test_sections_ordinary.py.
"""

import os
import sys

import pytest

import financial_analyzer as fa
from fundamental_express.cli.catalysts import resolve_analyst_notes_text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden", "fixtures"))
from ordinary_data import build_ordinary_data  # noqa: E402
from bank_data import build_bank_data  # noqa: E402
from reit_data import build_reit_data  # noqa: E402

from fundamental_express.reporting.sections_ordinary import build_ordinary_sections  # noqa: E402
from fundamental_express.reporting.sections_bank import build_bank_sections  # noqa: E402
from fundamental_express.reporting.sections_reit import build_reit_sections  # noqa: E402

NOTES = "Вывод аналитика: держать.\nВторая строка."

NOTES_WITH_HEADINGS = "# Заголовок\n\nТекст.\n\n## Подзаголовок\nДеталь."


def test_notes_headings_render_as_demoted_markdown_headings():
    sections = _ordinary_sections(NOTES_WITH_HEADINGS)
    md = sections[-1].markdown()
    assert "### Заголовок" in md
    assert "#### Подзаголовок" in md
    assert "> Текст." in md
    assert "> Деталь." in md
    assert "> #" not in md  # headings must not stay quoted literals


def test_notes_headings_render_as_pdf_heading_paragraphs():
    from reportlab.platypus import Paragraph
    sections = _ordinary_sections(NOTES_WITH_HEADINGS)
    flowables = sections[-1].flowables()
    texts = [f.text for f in flowables if isinstance(f, Paragraph)]
    assert any("Заголовок" in t for t in texts)
    assert any("Подзаголовок" in t for t in texts)
    assert not any(t.lstrip().startswith("##") for t in texts)


def test_notes_pdf_flowables_replace_emoji_with_plain_circle():
    from reportlab.platypus import Paragraph
    from fundamental_express.reporting.flowables import CalloutBox
    sections = _ordinary_sections("Вердикт 🟢 КУПИТЬ, балл 1.0.")
    texts = []
    for f in sections[-1].flowables():
        if isinstance(f, Paragraph):
            texts.append(f.text)
        elif isinstance(f, CalloutBox):
            texts.append(f._para.text)
    combined = "\n".join(texts)
    assert "🟢" not in combined
    assert "●" in combined


def test_notes_pdf_flowables_render_bold_and_bullets():
    from fundamental_express.reporting.flowables import CalloutBox
    sections = _ordinary_sections("Ключевое: **fair 266**.\n- пункт один\n- пункт два")
    boxes = [f for f in sections[-1].flowables() if isinstance(f, CalloutBox)]
    assert len(boxes) == 1
    assert "<b>fair 266</b>" in boxes[0]._para.text
    assert "• пункт один" in boxes[0]._para.text
    assert "• пункт два" in boxes[0]._para.text


def test_resolver_returns_none_by_default():
    assert resolve_analyst_notes_text() is None


def test_resolver_rejects_both_flags():
    with pytest.raises(SystemExit):
        resolve_analyst_notes_text("a", "b.txt")


def test_resolver_missing_file_exits_cleanly():
    with pytest.raises(SystemExit):
        resolve_analyst_notes_text(None, "no-such-file.txt")


def test_resolver_reads_file(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("  Текст из файла.  \n", encoding="utf-8")
    assert resolve_analyst_notes_text(None, str(p)) == "Текст из файла."


def _ordinary_sections(notes):
    data = build_ordinary_data()
    m = fa.compute_metrics(data)
    forward_outlook = fa.compute_forward_outlook(data.get("info", {}), m.valuation.price, m.eps, m.cagr)
    return build_ordinary_sections(
        m, forward_outlook, "Катализатор.",
        data["trading_currency"], data["price_kind"], data["quote_time_label"], "ACME", notes,
    )


def test_ordinary_without_notes_has_five_sections():
    assert len(_ordinary_sections(None)) == 5


def test_ordinary_with_notes_appends_section_six():
    sections = _ordinary_sections(NOTES)
    assert len(sections) == 6
    assert sections[-1].title == "Заметки аналитика"
    md = sections[-1].markdown()
    assert md.startswith("## 6. Заметки аналитика")
    assert "> Вывод аналитика: держать." in md
    assert len(sections[-1].flowables()) == 2  # intro paragraph + callout


def test_bank_with_notes_appends_section_five():
    data = build_bank_data()
    m = fa.compute_bank_metrics(data)
    assert len(build_bank_sections(
        m, "Катализатор.", data["trading_currency"],
        data["price_kind"], data["quote_time_label"], "GOLDBANK", None,
    )) == 4
    sections = build_bank_sections(
        m, "Катализатор.", data["trading_currency"],
        data["price_kind"], data["quote_time_label"], "GOLDBANK", NOTES,
    )
    assert len(sections) == 5
    assert sections[-1].markdown().startswith("## 5. Заметки аналитика")


def test_reit_with_notes_appends_section_five():
    data = build_reit_data()
    m = fa.compute_reit_metrics(data)
    assert len(build_reit_sections(
        m, "Катализатор.", data["trading_currency"],
        data["price_kind"], data["quote_time_label"], "PROPCO", None,
    )) == 4
    sections = build_reit_sections(
        m, "Катализатор.", data["trading_currency"],
        data["price_kind"], data["quote_time_label"], "PROPCO", NOTES,
    )
    assert len(sections) == 5
    assert sections[-1].markdown().startswith("## 5. Заметки аналитика")
