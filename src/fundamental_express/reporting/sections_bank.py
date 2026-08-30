"""Bank report sections (docs/spec/refactor-tasks.md T18): the same four
numbered blocks build_bank_markdown_report()/build_bank_pdf_report()
assemble inline today (checklist/verdict, NII/LTD table + structural
rows, DDM/ROE-P-B valuation disclosure, catalysts), rebuilt as an ordered
list[Section] from a BankMetrics. No forward-outlook section - Bank has
none today (see build_bank_markdown_report()).

Not yet wired into build_bank_markdown_report()/build_bank_pdf_report() -
pure addition, same posture as T17 (rollback = delete the two new files).
`_bank_valuation_disclosure`/`_bank_structural_rows` are duplicated from
financial_analyzer.py for the same reason as T17's `_debt_lines`.
"""

import pandas as pd
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Spacer

from fundamental_express.reporting.flowables import CalloutBox
from fundamental_express.reporting.sections import Section
from fundamental_express.reporting.tables import create_reportlab_table
from fundamental_express.reporting.theme import COLORS, FONT_NAME, USABLE_W


def _bank_valuation_disclosure(m):
    """Plain (label, value) pairs for the DDM/ROE-P-B model disclosure -
    shared between the markdown and flowables renderings of Section 3."""
    ke_line = (
        f"Ke = задано инвестором (--required-return) = {m.valuation.cost_of_equity * 100:.2f}%"
        if m.valuation.required_return_used
        else f"Ke = Rf + β×ERP = 4% + {m.valuation.beta:.2f}×5% = {m.valuation.cost_of_equity * 100:.2f}%"
    )
    if m.valuation.valuation_model == "DDM":
        return "Модель дисконтирования дивидендов (DDM)", [
            (ke_line, ""),
            ("Темп роста дивидендов (CAGR_div, ограничен 1.0%-8.0%)", f"{m.cagr_div * 100:.2f}%"),
            ("DPS последнего года (Common Dividends Paid / Diluted Shares)", f"{m.dps_last:.2f} USD"),
            ("Терминальный темп роста (Gordon Growth)", "2.5%"),
        ]
    return "Модель рентабельности капитала (ROE / P/B)", [
        (ke_line, ""),
        ("Балансовая стоимость на акцию (BVPS)", f"{m.bvps:.2f} USD"),
        ("Рентабельность капитала (ROE)", f"{m.roe * 100:.2f}%"),
    ]


def _bank_structural_rows(m, trading_ccy):
    """Loan-portfolio / deposit-base YoY table. 'N/A' for any row yfinance
    doesn't expose for this bank - never a fabricated 0."""
    def fmt(series):
        return ["N/A" if pd.isna(v) else f"{v / 1e6:,.1f}" for v in series]

    return [
        ["Net Loans (млн.)"] + fmt(m.net_loans),
        ["Allowance for Credit Losses (млн.)"] + fmt(m.loan_loss_allowance),
        ["Total Deposits (млн.)"] + fmt(m.total_deposits),
        ["LTD Ratio"] + [
            "N/A" if pd.isna(l) or pd.isna(d) or d == 0 else f"{(l / d) * 100:.1f}%"
            for l, d in zip(m.net_loans, m.total_deposits)
        ],
    ]


def _checklist_section(m):
    if m.scoring.sins:
        parts = []
        if m.scoring.critical_sins:
            parts.append("**Критические:**\n" + "\n".join(f"- {s.message}" for s in m.scoring.critical_sins))
        if m.scoring.minor_sins:
            parts.append(
                f"**Второстепенные (балл {m.scoring.minor_score:.1f} из {m.scoring.max_minor_score:.1f}):**\n"
                + "\n".join(f"- [{s.weight:.1f}] {s.message}" for s in m.scoring.minor_sins)
            )
        sins_block = "\n\n".join(parts)
    else:
        sins_block = "- Грехов не обнаружено."

    def markdown():
        return f"""## 1. Экспресс-вердикт и оценка рисков (банковский чеклист)

**{m.scoring.verdict}**

{m.scoring.reasoning}

**Выявленные риски:**

{sins_block}"""

    def flowables():
        verdict_style = ParagraphStyle(
            "VerdictText", fontName=FONT_NAME, fontSize=12, textColor=COLORS[m.scoring.verdict_color_key],
            leading=15, spaceAfter=6,
        )
        body_style = ParagraphStyle(
            "Body", fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6,
        )
        callout_style = ParagraphStyle(
            "CalloutText", fontName=FONT_NAME, fontSize=9, textColor=COLORS["body"], leading=13,
        )
        items = [
            Paragraph(m.scoring.verdict, verdict_style),
            Paragraph(m.scoring.reasoning, body_style),
        ]
        if m.scoring.sins:
            for s in m.scoring.sins:
                bar_color = COLORS["danger"] if s.tier == "critical" else COLORS["warning"]
                items.append(CalloutBox(s.message, USABLE_W, COLORS, callout_style, bar_color))
                items.append(Spacer(1, 4))
        else:
            items.append(Paragraph("Грехов не обнаружено.", body_style))
        return items

    return Section("Экспресс-вердикт и оценка рисков (банковский чеклист)", markdown, flowables)


def _fundamentals_section(m, trading_ccy):
    year_labels = m.year_labels

    def row(label, series, fmt="{:,.1f}"):
        return f"| {label} | " + " | ".join(
            "N/A" if pd.isna(v) else fmt.format(v) for v in series
        ) + " |"

    ltd_txt = "N/A" if m.ltd_ratio is None else f"{m.ltd_ratio * 100:.1f}%"
    de_txt = "N/A" if m.debt_to_equity is None else f"{m.debt_to_equity:.2f}x"
    struct_rows = _bank_structural_rows(m, trading_ccy)

    def markdown():
        return f"""## 2. Экспресс-анализ процентного дохода и баланса

Показатели в млн. {trading_ccy}. Вместо Revenue/Current Ratio для банков используются NII и Loan-to-Deposit (LTD).

| Показатель | {" | ".join(year_labels)} |
|---|{"---|" * len(year_labels)}
{row("Net Interest Income (NII)", m.net_interest_income / 1e6)}
{row("Комиссионный доход", m.commissions_income / 1e6)}
{row("Резервы под потери по кредитам (Provision)", m.credit_loss_provision / 1e6)}
{row("Чистая прибыль (Net Income)", m.net_income / 1e6)}
{row("Акционерный капитал (Shareholders Equity)", m.shareholders_equity / 1e6)}

**Loan-to-Deposit Ratio (LTD, последний год): {ltd_txt}** | **Total Debt / Shareholders Equity: {de_txt}**

### Структура кредитного портфеля и депозитной базы (YoY)

| Показатель | {" | ".join(year_labels)} |
|---|{"---|" * len(year_labels)}
{chr(10).join("| " + " | ".join(str(c) for c in r) + " |" for r in struct_rows)}"""

    def flowables():
        headers = ["Показатель"] + list(year_labels)
        rows = [
            ["Net Interest Income (NII)"] + ["N/A" if pd.isna(v) else f"{v / 1e6:,.1f}" for v in m.net_interest_income],
            ["Комиссионный доход"] + ["N/A" if pd.isna(v) else f"{v / 1e6:,.1f}" for v in m.commissions_income],
            ["Чистая прибыль (Net Income)"] + ["N/A" if pd.isna(v) else f"{v / 1e6:,.1f}" for v in m.net_income],
        ]
        return [
            create_reportlab_table(headers, rows, {}, COLORS),
            create_reportlab_table(["Показатель"] + list(year_labels), struct_rows, {}, COLORS),
        ]

    return Section("Экспресс-анализ процентного дохода и баланса", markdown, flowables)


def _valuation_section(m, trading_ccy, price_kind, quote_time_label):
    model_name, model_lines = _bank_valuation_disclosure(m)
    model_block = "\n".join(f"- {label}{': ' + value if value else ''}" for label, value in model_lines)

    def markdown():
        return f"""## 3. Оценка справедливой стоимости: {model_name}

{model_block}

**Справедливая стоимость акции: {m.valuation.fair_value_share:.2f} {trading_ccy}**
Последняя доступная рыночная котировка: {m.valuation.price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) | Статус: **{m.valuation.val_status}**"""

    def flowables():
        body_style = ParagraphStyle(
            "Body", fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6,
        )
        items = [Paragraph(label, body_style) for label, _ in model_lines]
        items.append(Paragraph(
            f"Справедливая стоимость акции: {m.valuation.fair_value_share:.2f} {trading_ccy}", body_style,
        ))
        return items

    return Section(f"Оценка справедливой стоимости: {model_name}", markdown, flowables)


def _catalysts_section(catalysts_text):
    catalysts_block = "\n".join(
        f"> {line}" if line.strip() else ">" for line in catalysts_text.splitlines()
    )

    def markdown():
        return f"""## 4. Катализаторы и риски (качественная оценка)

{catalysts_block}"""

    def flowables():
        body_style = ParagraphStyle(
            "Body", fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6,
        )
        return [Paragraph(catalysts_text.replace("\n", "<br/>"), body_style)]

    return Section("Катализаторы и риски", markdown, flowables)


def build_bank_sections(m, catalysts_text, trading_ccy, price_kind, quote_time_label):
    """Ordered list[Section] for the Bank report - the four numbered
    blocks build_bank_markdown_report()/build_bank_pdf_report() assemble
    inline today. No forward-outlook section (Bank has none)."""
    return [
        _checklist_section(m),
        _fundamentals_section(m, trading_ccy),
        _valuation_section(m, trading_ccy, price_kind, quote_time_label),
        _catalysts_section(catalysts_text),
    ]
