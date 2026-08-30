"""Ordinary report sections (docs/spec/refactor-tasks.md T17): the same
five numbered blocks build_markdown_report()/build_pdf_report() assemble
inline today (checklist/verdict, fundamentals table, DCF/DDM valuation +
sensitivity + debt disclosure, forward outlook, catalysts), rebuilt as an
ordered list[Section] from an OrdinaryMetrics.

Not yet wired into build_markdown_report()/build_pdf_report() - this is a
pure addition (T17's own rollback note requires a clean two-file delete),
verified by tests/test_sections_ordinary.py spot-checking content, not yet
by the golden markdown snapshot. `_debt_lines`/`LEASE_ASSUMPTION_NOTE` are
deliberately duplicated from financial_analyzer.py for the same reason
`Sin` was duplicated in T11 - they collapse into one copy once T19 deletes
the original build_markdown_report()/build_pdf_report().
"""

from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Spacer

from fundamental_express.domain.valuation import _peg_assessment
from fundamental_express.reporting.flowables import CalloutBox
from fundamental_express.reporting.sections import Section
from fundamental_express.reporting.tables import create_reportlab_table
from fundamental_express.reporting.theme import COLORS, FONT_NAME, FONT_BOLD, USABLE_W, _fmt_or_na

import pandas as pd

LEASE_ASSUMPTION_NOTE = (
    "Допущение по лизингу: в базовом DCF обязательства по аренде исключены из net debt, "
    "поскольку модель использует FCF после операционных арендных платежей. Это "
    "упрощающее допущение, а не универсальный бухгалтерский факт (выплаты по финансовой "
    "аренде могут классифицироваться иначе) - для сопоставлений, где lease liabilities "
    "рассматриваются как debt-like obligations, используйте альтернативный расчёт с "
    "Total Debt (включая аренду) вместо приведённого net debt."
)


def _debt_lines(m, trading_ccy):
    """Plain (label, value) pairs for the debt/net-debt disclosure - shared
    between the markdown and flowables renderings of Section 3 below."""
    lines = [(
        "Долгосрочный долг (Long Term Debt, только процентный долг)",
        f"{m.interest_bearing_debt / 1e9:,.2f} млрд. {trading_ccy}",
    )]
    if not pd.isna(m.lease_liabilities):
        lines.append((
            "Долгосрочные обязательства по аренде (Long-term lease liability, исключены из net debt ниже)",
            f"{m.lease_liabilities / 1e9:,.2f} млрд. {trading_ccy}",
        ))
    if not pd.isna(m.total_debt_incl_leases):
        lines.append((
            "Total Debt (агрегированное поле провайдера данных, включает долг и debt-like "
            "обязательства по его классификации - может не равняться простой сумме строк "
            "выше; справочно, не используется в DCF)",
            f"{m.total_debt_incl_leases / 1e9:,.2f} млрд. {trading_ccy}",
        ))
    lines.append((
        "Денежные средства (Cash and Cash Equivalents)",
        f"{m.cash_balance / 1e9:,.2f} млрд. {trading_ccy}",
    ))
    net_debt_label = (
        "Чистый долг, использован в DCF (поле Net Debt из Yahoo Finance)"
        if m.net_debt_source == "reported"
        else "Чистый долг, использован в DCF (расчёт: Долгосрочный долг − Кэш)"
    )
    lines.append((net_debt_label, f"{m.net_debt / 1e9:,.2f} млрд. {trading_ccy}"))
    return lines


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
        return f"""## 1. Экспресс-вердикт и оценка рисков

**{m.scoring.verdict}**

{m.scoring.reasoning}

**Выявленные риски:**

{sins_block}"""

    def flowables():
        verdict_style = ParagraphStyle(
            "VerdictText", fontName=FONT_BOLD, fontSize=12, textColor=COLORS[m.scoring.verdict_color_key],
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

    return Section("Экспресс-вердикт и оценка рисков", markdown, flowables)


def _fundamentals_section(m, trading_ccy):
    year_labels = m.year_labels

    def row(label, series, fmt="{:,.1f}"):
        return f"| {label} | " + " | ".join(fmt.format(v) for v in series) + " |"

    def markdown():
        table_rows = "\n".join([
            f"| Показатель | {' | '.join(year_labels)} |",
            "|---|" + "---|" * len(year_labels),
            row("Выручка (Revenue)", [v / 1e6 for v in m.revenue]),
            row("Операционная прибыль", [v / 1e6 for v in m.operating_income]),
            row("Чистая прибыль (Net Income)", [v / 1e6 for v in m.net_income]),
            row("Разводненная EPS, USD", list(m.eps), fmt="{:.2f}"),
            row("Оборотные активы", [v / 1e6 for v in m.curr_assets]),
            row("Краткосрочные обязательства", [v / 1e6 for v in m.curr_liab]),
            row("Current Ratio", list(m.curr_ratios), fmt="{:.2f}"),
            row("Акционерный капитал", [v / 1e6 for v in m.equity]),
            row("Free Cash Flow", [v / 1e6 for v in m.fcf]),
        ])
        return f"""## 2. Экспресс-анализ финансовых результатов и баланса

Показатели в млн. {trading_ccy}.

{table_rows}"""

    def flowables():
        headers = ["Показатель"] + list(year_labels)
        rows = [
            ["Выручка (Revenue)"] + [f"{v / 1e6:,.1f}" for v in m.revenue],
            ["Операционная прибыль"] + [f"{v / 1e6:,.1f}" for v in m.operating_income],
            ["Чистая прибыль (Net Income)"] + [f"{v / 1e6:,.1f}" for v in m.net_income],
            ["Разводненная EPS, USD"] + [f"{v:.2f}" for v in m.eps],
            ["Оборотные активы"] + [f"{v / 1e6:,.1f}" for v in m.curr_assets],
            ["Краткосрочные обязательства"] + [f"{v / 1e6:,.1f}" for v in m.curr_liab],
            ["Current Ratio"] + [f"{v:.2f}" for v in m.curr_ratios],
            ["Акционерный капитал"] + [f"{v / 1e6:,.1f}" for v in m.equity],
            ["Free Cash Flow"] + [f"{v / 1e6:,.1f}" for v in m.fcf],
        ]
        styles = {}
        return [create_reportlab_table(headers, rows, styles, COLORS)]

    return Section("Экспресс-анализ финансовых результатов и баланса", markdown, flowables)


def _valuation_section(m, trading_ccy, price_kind, quote_time_label):
    ke_disclosure = (
        f"Ke = задано инвестором (--required-return) = {m.valuation.cost_of_equity * 100:.2f}%"
        if m.valuation.required_return_used
        else f"Ke = Rf + β×ERP = 4% + {m.valuation.beta:.2f}×5% = {m.valuation.cost_of_equity * 100:.2f}%"
    )
    is_ddm = m.valuation.valuation_model == "DDM"

    def markdown():
        if is_ddm:
            return f"""## 3. Оценка справедливой стоимости (Модель DDM)

⚠️ **Внимание:** Применена модель дисконтирования дивидендов (DDM) вместо классического DCF - у компании искажена структура капитала (отрицательный или "перегруженный" долгом акционерный капитал) на фоне стабильной истории дивидендных выплат. Классический FCF-DCF в этом случае занижает стоимость (лизинговые/долговые обязательства искажают WACC).

- {ke_disclosure}
- Темп роста дивидендов (CAGR_div, ограничен 2.0%-10.0%): {m.cagr_div * 100:.2f}%
- DPS последнего года (Dividends Paid / Diluted Shares): {m.dps_last:.2f} {trading_ccy}
- Терминальный темп роста (Gordon Growth): 2.5%

**Справедливая стоимость по DDM: {m.valuation.fair_value_share:.2f} {trading_ccy}**
Текущая рыночная цена: {m.valuation.price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) | Статус: **{m.valuation.val_status}**"""

        debt_block = "\n".join(f"- {label}: {value}" for label, value in _debt_lines(m, trading_ccy))
        sens_header = "| " + " | ".join(m.sensitivity_headers) + " |"
        sens_sep = "|" + "---|" * len(m.sensitivity_headers)
        sens_rows = "\n".join("| " + " | ".join(r) + " |" for r in m.sensitivity_rows)
        return f"""## 3. Модель дисконтирования денежных потоков (DCF)

- Стоимость собственного капитала: {ke_disclosure}
- Стоимость долга после налога: Kd×(1-T) = 4.5%×(1-21%) = {m.cost_of_debt_after_tax * 100:.2f}% (Kd=4.5% и T=21% — фиксированные допущения методики, не специфичны для компании и не эффективная налоговая ставка компании)
- Веса структуры капитала (по рыночной капитализации): E/(D+E) = {m.equity_weight * 100:.1f}%, D/(D+E) = {m.debt_weight * 100:.1f}%
- **WACC:** {m.equity_weight * 100:.1f}%×{m.valuation.cost_of_equity * 100:.2f}% + {m.debt_weight * 100:.1f}%×{m.cost_of_debt_after_tax * 100:.2f}% = **{m.wacc * 100:.2f}%**
- CAGR роста FCF: {m.cagr * 100:.2f}% (историческая, ограничена 2-15%)
- Терминальный темп роста: 2.5%

{debt_block}

> {LEASE_ASSUMPTION_NOTE}

- Enterprise Value: {m.enterprise_value / 1e9:,.2f} млрд. {trading_ccy}
- Equity Value: {m.equity_value / 1e9:,.2f} млрд. {trading_ccy}

**Справедливая стоимость акции: {m.valuation.fair_value_share:.2f} {trading_ccy}**
Последняя доступная рыночная котировка: {m.valuation.price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) | Статус: **{m.valuation.val_status}**

### Матрица чувствительности (г — рост явного 5-летнего прогноза FCF; терминальный рост фиксирован на 2.5% и используется только в формуле Гордона — условие WACC > g не требуется для этой матрицы)

{sens_header}
{sens_sep}
{sens_rows}"""

    def flowables():
        body_style = ParagraphStyle(
            "Body", fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6,
        )
        items = [Paragraph(ke_disclosure, body_style)]
        if is_ddm:
            items.append(Paragraph(
                f"Справедливая стоимость по DDM: {m.valuation.fair_value_share:.2f} {trading_ccy}", body_style,
            ))
        else:
            items.append(Paragraph(f"WACC: {m.wacc * 100:.2f}%", body_style))
            items.append(create_reportlab_table(
                ["Строка", "Значение"], _debt_lines(m, trading_ccy), {}, COLORS,
            ))
            items.append(create_reportlab_table(
                m.sensitivity_headers, m.sensitivity_rows, {}, COLORS,
            ))
        return items

    return Section("Оценка справедливой стоимости", markdown, flowables)


def _forward_outlook_section(forward_outlook):
    peg_color_key, peg_label = _peg_assessment(forward_outlook["peg_ratio"])
    peg_emoji = {"success": "🟢", "warning": "🟡", "danger": "🔴", "muted": "⚪"}[peg_color_key]
    forward_pe_txt = _fmt_or_na(forward_outlook["forward_pe"])
    growth_txt = _fmt_or_na(forward_outlook["growth_pct"], "{:.1f}%")
    peg_txt = _fmt_or_na(forward_outlook["peg_ratio"])

    def markdown():
        return f"""## 4. Форвардные мультипликаторы и консенсус-прогноз

> Раздел носит справочный характер и не влияет на балл экспресс-чеклиста из раздела 1 — это форвардный (консенсусный) взгляд, балансирующий DCF-модель, построенную на экстраполяции исторических 4 лет.

- Forward P/E: **{forward_pe_txt}** [источник: {forward_outlook['forward_pe_source'] or 'N/A'}]
- Ожидаемый рост (консенсус): **{growth_txt}** [источник: {forward_outlook['growth_source'] or 'N/A'}]
- PEG Ratio: **{peg_txt}** {peg_emoji} — {peg_label} [источник: {forward_outlook['peg_source'] or 'N/A'}]"""

    def flowables():
        body_style = ParagraphStyle(
            "Body", fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6,
        )
        return [
            Paragraph(f"Forward P/E: {forward_pe_txt}", body_style),
            Paragraph(f"Ожидаемый рост: {growth_txt}", body_style),
            Paragraph(f"PEG Ratio: {peg_txt} {peg_emoji} — {peg_label}", body_style),
        ]

    return Section("Форвардные мультипликаторы и консенсус-прогноз", markdown, flowables)


def _catalysts_section(catalysts_text):
    catalysts_block = "\n".join(
        f"> {line}" if line.strip() else ">" for line in catalysts_text.splitlines()
    )

    def markdown():
        return f"""## 5. Катализаторы и риски (качественная оценка)

{catalysts_block}"""

    def flowables():
        body_style = ParagraphStyle(
            "Body", fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6,
        )
        return [Paragraph(catalysts_text.replace("\n", "<br/>"), body_style)]

    return Section("Катализаторы и риски", markdown, flowables)


def build_ordinary_sections(m, forward_outlook, catalysts_text, trading_ccy, price_kind, quote_time_label):
    """Ordered list[Section] for the Ordinary report - the five numbered
    blocks build_markdown_report()/build_pdf_report() assemble inline
    today. Sector-warning-banner handling stays out of scope here (it's a
    header-level concern, not a numbered section - see
    docs/spec/refactor-architecture-spec.md Section 5)."""
    return [
        _checklist_section(m),
        _fundamentals_section(m, trading_ccy),
        _valuation_section(m, trading_ccy, price_kind, quote_time_label),
        _forward_outlook_section(forward_outlook),
        _catalysts_section(catalysts_text),
    ]
