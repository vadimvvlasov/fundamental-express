"""Bank section-model tests (docs/spec/refactor-tasks.md T18).

Same style as tests/test_sections_ordinary.py: builds a real BankMetrics
via financial_analyzer.compute_bank_metrics() on the existing network-free
golden fixture, renders each Section standalone, spot-checks content -
not yet a byte-exact diff against the golden snapshot (T19).
"""

import os
import sys

import financial_analyzer as fa

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden", "fixtures"))
from bank_data import build_bank_data  # noqa: E402

from fundamental_express.reporting.sections_bank import build_bank_sections


def _sections():
    data = build_bank_data()
    m = fa.compute_bank_metrics(data)
    sections = build_bank_sections(
        m, "Тестовый катализатор.", data["trading_currency"], data["price_kind"], data["quote_time_label"], "GOLDBANK",
    )
    return m, sections


def test_returns_four_sections_in_order_with_no_forward_outlook():
    _, sections = _sections()
    assert [s.title for s in sections] == [
        "Экспресс-вердикт и оценка рисков (банковский чеклист)",
        "Экспресс-анализ процентного дохода и баланса",
        "Оценка справедливой стоимости: Модель дисконтирования дивидендов (DDM)",
        "Катализаторы и риски",
    ]


def test_checklist_section_markdown_reflects_verdict_and_zero_sins():
    m, sections = _sections()
    md = sections[0].markdown()
    assert md.startswith("## 1. Экспресс-вердикт и оценка рисков (банковский чеклист)")
    assert m.scoring.verdict in md
    assert "Грехов не обнаружено." in md  # fixture is a clean BUY, zero sins


def test_checklist_section_flowables_render_without_error():
    _, sections = _sections()
    assert len(sections[0].flowables()) >= 4


def test_fundamentals_section_has_nii_and_ltd_table():
    _, sections = _sections()
    md = sections[1].markdown()
    assert md.startswith("## 2. Экспресс-анализ процентного дохода и баланса")
    assert "Net Interest Income (NII)" in md
    assert "Loan-to-Deposit Ratio" in md


def test_fundamentals_section_flowables_includes_tables_and_chart():
    _, sections = _sections()
    # intro para + NII table + LTD para + chart image + struct para + struct table
    assert len(sections[1].flowables()) >= 6


def test_valuation_section_uses_ddm_when_dividends_paid():
    m, sections = _sections()
    assert m.valuation.valuation_model == "DDM"  # fixture pays dividends
    md = sections[2].markdown()
    assert "## 3. Оценка справедливой стоимости: Модель дисконтирования дивидендов (DDM)" in md
    assert f"{m.valuation.fair_value_share:.2f}" in md


def test_catalysts_section_quotes_the_supplied_text():
    _, sections = _sections()
    md = sections[3].markdown()
    assert md.startswith("## 4. Катализаторы и риски")
    assert "> Тестовый катализатор." in md
