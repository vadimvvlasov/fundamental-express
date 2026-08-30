"""Ordinary section-model tests (docs/spec/refactor-tasks.md T17).

Builds a real OrdinaryMetrics via financial_analyzer.compute_metrics() on
the same network-free fixture the golden-markdown harness uses, then
renders each Section standalone and spot-checks its markdown/flowables
content - not yet a byte-exact diff against the golden snapshot (that's
T19's job, once these sections are actually wired into the renderer).
"""

import os
import sys

import financial_analyzer as fa

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden", "fixtures"))
from ordinary_data import build_ordinary_data  # noqa: E402

from fundamental_express.reporting.sections_ordinary import build_ordinary_sections


def _sections():
    data = build_ordinary_data()
    m = fa.compute_metrics(data)
    forward_outlook = fa.compute_forward_outlook(data.get("info", {}), m.valuation.price, m.eps, m.cagr)
    sections = build_ordinary_sections(
        m, forward_outlook, "Тестовый катализатор.",
        data["trading_currency"], data["price_kind"], data["quote_time_label"],
    )
    return m, sections


def test_returns_five_sections_in_order():
    _, sections = _sections()
    assert [s.title for s in sections] == [
        "Экспресс-вердикт и оценка рисков",
        "Экспресс-анализ финансовых результатов и баланса",
        "Оценка справедливой стоимости",
        "Форвардные мультипликаторы и консенсус-прогноз",
        "Катализаторы и риски",
    ]


def test_checklist_section_markdown_reflects_verdict_and_zero_sins():
    m, sections = _sections()
    md = sections[0].markdown()
    assert md.startswith("## 1. Экспресс-вердикт и оценка рисков")
    assert m.scoring.verdict in md
    assert m.scoring.reasoning in md
    assert "Грехов не обнаружено." in md  # fixture is a clean BUY, zero sins


def test_checklist_section_flowables_render_without_error():
    _, sections = _sections()
    flowables = sections[0].flowables()
    assert len(flowables) >= 2  # verdict paragraph + reasoning paragraph at minimum


def test_fundamentals_section_table_has_a_row_per_metric():
    _, sections = _sections()
    md = sections[1].markdown()
    assert md.startswith("## 2. Экспресс-анализ финансовых результатов и баланса")
    for label in ["Выручка (Revenue)", "Операционная прибыль", "Free Cash Flow", "Current Ratio"]:
        assert label in md


def test_fundamentals_section_flowables_is_one_table():
    _, sections = _sections()
    flowables = sections[1].flowables()
    assert len(flowables) == 1


def test_valuation_section_uses_dcf_when_model_is_dcf():
    m, sections = _sections()
    assert m.valuation.valuation_model == "DCF"  # fixture has no dividend/distress signal
    md = sections[2].markdown()
    assert "## 3. Модель дисконтирования денежных потоков (DCF)" in md
    assert "WACC" in md
    assert "Матрица чувствительности" in md
    assert f"{m.valuation.fair_value_share:.2f}" in md


def test_forward_outlook_section_reports_na_when_no_consensus_data():
    _, sections = _sections()
    md = sections[3].markdown()
    assert md.startswith("## 4. Форвардные мультипликаторы и консенсус-прогноз")
    assert "Forward P/E" in md
    assert "PEG Ratio" in md


def test_catalysts_section_quotes_the_supplied_text():
    _, sections = _sections()
    md = sections[4].markdown()
    assert md.startswith("## 5. Катализаторы и риски")
    assert "> Тестовый катализатор." in md
