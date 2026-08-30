"""Bank report sections (docs/spec/refactor-tasks.md T18/T20): the same
four numbered blocks build_bank_markdown_report()/build_bank_pdf_report()
assemble inline today (checklist/verdict, NII/LTD table + structural
rows, DDM/ROE-P-B valuation disclosure, catalysts), rebuilt as an ordered
list[Section] from a BankMetrics. No forward-outlook section - Bank has
none today.

`markdown()` is verified byte-for-byte against the golden snapshot (T19).
`flowables()` was upgraded in T20 to match build_bank_pdf_report()'s
actual content/richness (grouped sin callouts, the NII chart image, the
structural table) - PDF output was never byte-comparable, so this is a
structural/visual match verified by generating a real PDF, not a diff.
`_bank_valuation_disclosure`/`_bank_structural_rows` are duplicated from
financial_analyzer.py for the same reason as T17's `_debt_lines`.
"""

import pandas as pd
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, Paragraph, Spacer

from fundamental_express.reporting.charts import generate_nii_chart
from fundamental_express.reporting.flowables import CalloutBox
from fundamental_express.reporting.sections import Section
from fundamental_express.reporting.tables import create_reportlab_table
from fundamental_express.reporting.theme import COLORS, FONT_NAME, USABLE_W

_BODY = dict(fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6)
_CALLOUT_TEXT = dict(fontName=FONT_NAME, fontSize=9, textColor=COLORS["body"], leading=13)


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
        body_style = ParagraphStyle("Body", **_BODY)
        callout_style = ParagraphStyle("CalloutText", **_CALLOUT_TEXT)
        items = [
            Paragraph("<b>Итоговое решение по алгоритму:</b>", body_style),
            Paragraph(m.scoring.verdict, verdict_style),
            Paragraph(f"<b>Резюме и обоснование:</b> {m.scoring.reasoning}", body_style),
        ]
        if m.scoring.critical_sins:
            crit_text = (
                "<b>Критические риски (любой из них — основание для ПРОПУСТИТЬ):</b><br/>"
                + "<br/>".join(f"• {s.message}" for s in m.scoring.critical_sins)
            )
            items.append(CalloutBox(crit_text, USABLE_W, COLORS, callout_style, COLORS["danger"]))
            items.append(Spacer(1, 6))
        if m.scoring.minor_sins:
            minor_text = (
                f"<b>Второстепенные риски (балл {m.scoring.minor_score:.1f} из {m.scoring.max_minor_score:.1f}):</b><br/>"
                + "<br/>".join(f"• [{s.weight:.1f}] {s.message}" for s in m.scoring.minor_sins)
            )
            items.append(CalloutBox(minor_text, USABLE_W, COLORS, callout_style, COLORS["warning"]))
        if not m.scoring.sins:
            items.append(CalloutBox(
                "<b>Финансовые риски:</b> Грехов не обнаружено. Показатели банка в безупречной форме.",
                USABLE_W, COLORS, callout_style, COLORS["success"],
            ))
        return items

    return Section("Экспресс-вердикт и оценка рисков (банковский чеклист)", markdown, flowables)


def _fundamentals_section(m, trading_ccy, ticker):
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
        body_style = ParagraphStyle("Body", **_BODY)
        last4 = range(len(year_labels) - 4, len(year_labels))
        headers = [f"Показатель (в млн. {trading_ccy})"] + [year_labels[i] for i in last4]

        def fmt_last4(series):
            return ["N/A" if pd.isna(series.iloc[i]) else f"{series.iloc[i] / 1e6:,.1f}" for i in last4]

        rows = [
            ["Net Interest Income (NII)"] + fmt_last4(m.net_interest_income),
            ["Комиссионный доход"] + fmt_last4(m.commissions_income),
            ["Резервы под потери по кредитам"] + fmt_last4(m.credit_loss_provision),
            ["Чистая прибыль (Net Income)"] + fmt_last4(m.net_income),
            ["Акционерный капитал (Shareholders Equity)"] + fmt_last4(m.shareholders_equity),
        ]
        chart_img_path = generate_nii_chart(year_labels, m.net_interest_income.values, ticker)
        return [
            Paragraph(
                "Вместо Revenue/Current Ratio (неприменимых к банкам) используются Net Interest Income (NII) и "
                "Loan-to-Deposit Ratio (LTD).",
                body_style,
            ),
            create_reportlab_table(headers, rows, {}, COLORS, col_widths=[190, 70, 70, 70, 70]),
            Spacer(1, 8),
            Paragraph(
                f"<b>Loan-to-Deposit Ratio (LTD, последний год):</b> {ltd_txt} &nbsp;&nbsp; "
                f"<b>Total Debt / Shareholders Equity:</b> {de_txt} "
                "(у банков нет Enterprise Value/Net Debt в классическом смысле).",
                body_style,
            ),
            Spacer(1, 8),
            Image(chart_img_path, width=USABLE_W, height=USABLE_W * 0.4),
            Spacer(1, 10),
            Paragraph("<b>Структура кредитного портфеля и депозитной базы (YoY):</b>", body_style),
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
        callout_style = ParagraphStyle("CalloutText", **_CALLOUT_TEXT)
        val_color = COLORS[m.valuation.val_color_key]
        model_html = "<br/>".join(
            f"• <b>{label}</b>{': ' + value if value else ''}" for label, value in model_lines
        )
        val_banner_text = (
            f"<b>СПРАВЕДЛИВАЯ СТОИМОСТЬ АКЦИИ: {m.valuation.fair_value_share:.2f} {trading_ccy}</b><br/>"
            f"Последняя доступная рыночная котировка: {m.valuation.price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) "
            f"| Статус: <font color='{val_color.hexval()}'><b>{m.valuation.val_status}</b></font>"
        )
        return [
            CalloutBox(model_html, USABLE_W, COLORS, callout_style, COLORS["accent"]),
            Spacer(1, 8),
            CalloutBox(
                val_banner_text, USABLE_W, COLORS,
                ParagraphStyle("ValB", parent=callout_style, fontSize=10, leading=14), val_color,
            ),
        ]

    return Section(f"Оценка справедливой стоимости: {model_name}", markdown, flowables)


def _catalysts_section(catalysts_text):
    catalysts_block = "\n".join(
        f"> {line}" if line.strip() else ">" for line in catalysts_text.splitlines()
    )

    def markdown():
        return f"""## 4. Катализаторы и риски (качественная оценка)

{catalysts_block}"""

    def flowables():
        callout_style = ParagraphStyle("CalloutText", **_CALLOUT_TEXT)
        catalysts_html = "<br/>".join(catalysts_text.splitlines())
        return [CalloutBox(catalysts_html, USABLE_W, COLORS, callout_style, COLORS["muted"])]

    return Section("Катализаторы и риски", markdown, flowables)


def build_bank_sections(m, catalysts_text, trading_ccy, price_kind, quote_time_label, ticker):
    """Ordered list[Section] for the Bank report - the four numbered
    blocks build_bank_markdown_report()/build_bank_pdf_report() assemble
    inline today. No forward-outlook section (Bank has none)."""
    return [
        _checklist_section(m),
        _fundamentals_section(m, trading_ccy, ticker),
        _valuation_section(m, trading_ccy, price_kind, quote_time_label),
        _catalysts_section(catalysts_text),
    ]
