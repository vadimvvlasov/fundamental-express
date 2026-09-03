"""REIT report sections (docs/spec/refactor-tasks.md T18/T20): the same
four numbered blocks build_reit_markdown_report()/build_reit_pdf_report()
assemble inline today (checklist/verdict, FFO/AFFO/NOI operating table,
NAV valuation bridge, catalysts), rebuilt as an ordered list[Section]
from a ReitMetrics. No forward-outlook section - REIT has none today.

`markdown()` is verified byte-for-byte against the golden snapshot (T19).
`flowables()` was upgraded in T20 to match build_reit_pdf_report()'s
actual content/richness (grouped sin callouts, the FFO/AFFO chart image,
the NAV bridge as one callout) - PDF output was never byte-comparable, so
this is a structural/visual match verified by generating a real PDF, not
a diff. `_reit_nav_bridge_rows`/`_reit_operating_rows` are duplicated
from financial_analyzer.py for the same reason as T17's `_debt_lines`.
"""

import pandas as pd
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, Paragraph, Spacer

from fundamental_express.reporting.charts import generate_ffo_chart
from fundamental_express.reporting.flowables import CalloutBox
from fundamental_express.reporting.sections import Section
from fundamental_express.reporting.tables import create_reportlab_table
from fundamental_express.reporting.theme import COLORS, FONT_NAME, USABLE_W

_BODY = dict(fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6)
_CALLOUT_TEXT = dict(fontName=FONT_NAME, fontSize=9, textColor=COLORS["body"], leading=13)


def _reit_nav_bridge_rows(m, trading_ccy):
    """Plain (label, value) pairs for the NAV bridge - shared between the
    markdown and flowables renderings of Section 3."""
    return [
        ("NOI (последний год)", f"{m.noi.iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
        (
            f"NOI, использован в Property Value (среднее за {m.avg_noi_years} "
            f"{'год' if m.avg_noi_years == 1 else 'года' if m.avg_noi_years < 5 else 'лет'})",
            f"{m.avg_noi / 1e6:,.1f} млн. {trading_ccy}",
        ),
        ("Применённый Cap Rate", f"{m.cap_rate * 100:.2f}% ({m.cap_rate_label})"),
        ("Property Value = NOI / Cap Rate", f"{m.property_value / 1e6:,.1f} млн. {trading_ccy}"),
        ("Плюс: Cash", f"{m.cash.iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
        ("Плюс: Receivables", f"{m.receivables.iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
        ("Плюс: Construction in Progress", f"{m.construction_in_progress.iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
        ("Минус: Total Liabilities", f"{m.total_liab.iloc[-1] / 1e6:,.1f} млн. {trading_ccy}" if not pd.isna(m.total_liab.iloc[-1]) else "N/A"),
        ("= Net Asset Value (NAV)", f"{m.nav / 1e6:,.1f} млн. {trading_ccy}"),
    ]


def _reit_operating_rows(m):
    def fmt(series):
        return ["N/A" if pd.isna(v) else f"{v / 1e6:,.1f}" for v in series]

    return [
        ["FFO (млн.)"] + fmt(m.ffo),
        ["AFFO (млн.)"] + fmt(m.affo),
        ["NOI (млн.)"] + fmt(m.noi),
        ["CapEx (млн.)"] + fmt(m.capex.abs()),
        ["Dividends Paid (млн.)"] + fmt(m.dividends_paid),
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
        return f"""## 1. Экспресс-вердикт и оценка рисков (чеклист REIT)

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
                "<b>Финансовые риски:</b> Грехов не обнаружено. Показатели REIT в безупречной форме.",
                USABLE_W, COLORS, callout_style, COLORS["success"],
            ))
        return items

    return Section("Экспресс-вердикт и оценка рисков (чеклист REIT)", markdown, flowables)


def _operating_section(m, trading_ccy, ticker):
    year_labels = m.year_labels
    op_rows = _reit_operating_rows(m)
    payout_txt = "N/A (дивиденды не выплачиваются)" if m.affo_payout_ratio is None else (
        "∞ (AFFO ≤ 0)" if m.affo_payout_ratio == float("inf") else f"{m.affo_payout_ratio * 100:.1f}%"
    )
    de_txt = "N/A" if m.debt_to_equity is None else f"{m.debt_to_equity:.2f}x"

    def markdown():
        return f"""## 2. REIT Operating Performance (FFO / AFFO / NOI)

Показатели в млн. {trading_ccy}. Вместо Net Income/операционного кэш-флоу для REIT используются FFO, AFFO и NOI.

| Показатель | {" | ".join(year_labels)} |
|---|{"---|" * len(year_labels)}
{chr(10).join("| " + " | ".join(str(c) for c in r) + " |" for r in op_rows)}

**Occupancy Rate: {m.occupancy_rate * 100:.1f}%** | **AFFO Payout Ratio: {payout_txt}** | **Total Debt / Shareholders Equity: {de_txt}**"""

    def flowables():
        body_style = ParagraphStyle("Body", **_BODY)
        last4 = range(len(year_labels) - 4, len(year_labels))
        headers = [f"Показатель (в млн. {trading_ccy})"] + [year_labels[i] for i in last4]

        def fmt_last4(series):
            return ["N/A" if pd.isna(series.iloc[i]) else f"{series.iloc[i] / 1e6:,.1f}" for i in last4]

        rows = [
            ["FFO"] + fmt_last4(m.ffo),
            ["AFFO"] + fmt_last4(m.affo),
            ["NOI"] + fmt_last4(m.noi),
            ["CapEx"] + fmt_last4(m.capex.abs()),
            ["Dividends Paid"] + fmt_last4(m.dividends_paid),
        ]
        chart_img_path = generate_ffo_chart(year_labels, m.ffo.values, m.affo.values, ticker)
        return [
            Paragraph(
                "Net Income искажён бумажной амортизацией недвижимости - вместо него используются FFO, AFFO и NOI.",
                body_style,
            ),
            create_reportlab_table(headers, rows, {}, COLORS, col_widths=[190, 70, 70, 70, 70]),
            Spacer(1, 8),
            Paragraph(
                f"<b>Occupancy Rate:</b> {m.occupancy_rate * 100:.1f}% &nbsp;&nbsp; "
                f"<b>AFFO Payout Ratio:</b> {payout_txt} &nbsp;&nbsp; "
                f"<b>Total Debt / Shareholders Equity:</b> {de_txt}",
                body_style,
            ),
            Spacer(1, 8),
            Image(chart_img_path, width=USABLE_W, height=USABLE_W * 0.4),
        ]

    return Section("REIT Operating Performance (FFO / AFFO / NOI)", markdown, flowables)


def _valuation_section(m, trading_ccy, price_kind, quote_time_label):
    nav_rows = _reit_nav_bridge_rows(m, trading_ccy)
    nav_block = "\n".join(f"- {label}: {value}" for label, value in nav_rows)

    def markdown():
        return f"""## 3. NAV Valuation Bridge

{nav_block}

**Справедливая стоимость акции: {m.valuation.fair_value_share:.2f} {trading_ccy}**
Последняя доступная рыночная котировка: {m.valuation.price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) | Статус: **{m.valuation.val_status}**"""

    def flowables():
        callout_style = ParagraphStyle("CalloutText", **_CALLOUT_TEXT)
        val_color = COLORS[m.valuation.val_color_key]
        nav_html = "<br/>".join(f"• <b>{label}:</b> {value}" for label, value in nav_rows)
        val_banner_text = (
            f"<b>СПРАВЕДЛИВАЯ СТОИМОСТЬ АКЦИИ: {m.valuation.fair_value_share:.2f} {trading_ccy}</b><br/>"
            f"Последняя доступная рыночная котировка: {m.valuation.price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) "
            f"| Статус: <font color='{val_color.hexval()}'><b>{m.valuation.val_status}</b></font>"
        )
        return [
            CalloutBox(nav_html, USABLE_W, COLORS, callout_style, COLORS["accent"]),
            Spacer(1, 8),
            CalloutBox(
                val_banner_text, USABLE_W, COLORS,
                ParagraphStyle("ValB", parent=callout_style, fontSize=10, leading=14), val_color,
            ),
        ]

    return Section("NAV Valuation Bridge", markdown, flowables)


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


def build_reit_sections(m, catalysts_text, trading_ccy, price_kind, quote_time_label, ticker):
    """Ordered list[Section] for the REIT report - the four numbered
    blocks build_reit_markdown_report()/build_reit_pdf_report() assemble
    inline today. No forward-outlook section (REIT has none)."""
    return [
        _checklist_section(m),
        _operating_section(m, trading_ccy, ticker),
        _valuation_section(m, trading_ccy, price_kind, quote_time_label),
        _catalysts_section(catalysts_text),
    ]
