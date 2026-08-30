"""REIT report sections (docs/spec/refactor-tasks.md T18): the same four
numbered blocks build_reit_markdown_report()/build_reit_pdf_report()
assemble inline today (checklist/verdict, FFO/AFFO/NOI operating table,
NAV valuation bridge, catalysts), rebuilt as an ordered list[Section]
from a ReitMetrics. No forward-outlook section - REIT has none today
(see build_reit_markdown_report()).

Not yet wired into build_reit_markdown_report()/build_reit_pdf_report() -
pure addition, same posture as T17 (rollback = delete the two new files).
`_reit_nav_bridge_rows`/`_reit_operating_rows` are duplicated from
financial_analyzer.py for the same reason as T17's `_debt_lines`.
"""

import pandas as pd
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Spacer

from fundamental_express.reporting.flowables import CalloutBox
from fundamental_express.reporting.sections import Section
from fundamental_express.reporting.tables import create_reportlab_table
from fundamental_express.reporting.theme import COLORS, FONT_NAME, USABLE_W


def _reit_nav_bridge_rows(m, trading_ccy):
    """Plain (label, value) pairs for the NAV bridge - shared between the
    markdown and flowables renderings of Section 3."""
    return [
        ("NOI (последний год)", f"{m.noi.iloc[-1] / 1e6:,.1f} млн. {trading_ccy}"),
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

    return Section("Экспресс-вердикт и оценка рисков (чеклист REIT)", markdown, flowables)


def _operating_section(m, trading_ccy):
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
        return [create_reportlab_table(["Показатель"] + list(year_labels), op_rows, {}, COLORS)]

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
        body_style = ParagraphStyle(
            "Body", fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6,
        )
        items = [Paragraph(f"{label}: {value}", body_style) for label, value in nav_rows]
        items.append(Paragraph(
            f"Справедливая стоимость акции: {m.valuation.fair_value_share:.2f} {trading_ccy}", body_style,
        ))
        return items

    return Section("NAV Valuation Bridge", markdown, flowables)


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


def build_reit_sections(m, catalysts_text, trading_ccy, price_kind, quote_time_label):
    """Ordered list[Section] for the REIT report - the four numbered
    blocks build_reit_markdown_report()/build_reit_pdf_report() assemble
    inline today. No forward-outlook section (REIT has none)."""
    return [
        _checklist_section(m),
        _operating_section(m, trading_ccy),
        _valuation_section(m, trading_ccy, price_kind, quote_time_label),
        _catalysts_section(catalysts_text),
    ]
