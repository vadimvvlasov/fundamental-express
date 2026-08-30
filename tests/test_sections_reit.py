"""REIT section-model tests (docs/spec/refactor-tasks.md T18).

Same style as tests/test_sections_ordinary.py: builds a real ReitMetrics
via financial_analyzer.compute_reit_metrics() on the existing network-free
golden fixture, renders each Section standalone, spot-checks content -
not yet a byte-exact diff against the golden snapshot (T19).
"""

import os
import sys

import financial_analyzer as fa

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden", "fixtures"))
from reit_data import build_reit_data  # noqa: E402

from fundamental_express.reporting.sections_reit import build_reit_sections


def _sections():
    data = build_reit_data()
    m = fa.compute_reit_metrics(data)
    sections = build_reit_sections(
        m, "Тестовый катализатор.", data["trading_currency"], data["price_kind"], data["quote_time_label"], "PROPCO",
    )
    return m, sections


def test_returns_four_sections_in_order_with_no_forward_outlook():
    _, sections = _sections()
    assert [s.title for s in sections] == [
        "Экспресс-вердикт и оценка рисков (чеклист REIT)",
        "REIT Operating Performance (FFO / AFFO / NOI)",
        "NAV Valuation Bridge",
        "Катализаторы и риски",
    ]


def test_checklist_section_markdown_reflects_verdict_and_zero_sins():
    m, sections = _sections()
    md = sections[0].markdown()
    assert md.startswith("## 1. Экспресс-вердикт и оценка рисков (чеклист REIT)")
    assert m.scoring.verdict in md
    assert "Грехов не обнаружено." in md  # fixture is a clean BUY, zero sins


def test_checklist_section_flowables_render_without_error():
    _, sections = _sections()
    assert len(sections[0].flowables()) >= 4


def test_operating_section_has_ffo_affo_noi_rows():
    _, sections = _sections()
    md = sections[1].markdown()
    assert md.startswith("## 2. REIT Operating Performance (FFO / AFFO / NOI)")
    for label in ["FFO (млн.)", "AFFO (млн.)", "NOI (млн.)"]:
        assert label in md
    assert "Occupancy Rate" in md


def test_operating_section_flowables_includes_table_and_chart():
    _, sections = _sections()
    assert len(sections[1].flowables()) >= 3  # intro paragraph + table + chart image at minimum


def test_valuation_section_has_nav_bridge():
    m, sections = _sections()
    md = sections[2].markdown()
    assert "## 3. NAV Valuation Bridge" in md
    assert "Net Asset Value (NAV)" in md
    assert f"{m.valuation.fair_value_share:.2f}" in md


def test_catalysts_section_quotes_the_supplied_text():
    _, sections = _sections()
    md = sections[3].markdown()
    assert md.startswith("## 4. Катализаторы и риски")
    assert "> Тестовый катализатор." in md
