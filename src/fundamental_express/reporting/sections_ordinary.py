"""Ordinary report sections (docs/spec/refactor-tasks.md T17/T20): the same
five numbered blocks build_markdown_report()/build_pdf_report() assemble
inline today (checklist/verdict, fundamentals table, DCF/DDM valuation +
sensitivity + debt disclosure, forward outlook, catalysts), rebuilt as an
ordered list[Section] from an OrdinaryMetrics.

`markdown()` is verified byte-for-byte against the golden snapshot (T19).
`flowables()` was upgraded in T20 to match build_pdf_report()'s actual
content/richness (grouped sin callouts, the chart image, the combined
DCF/DDM disclosure callout, the projected-FCF and sensitivity tables) -
PDF output was never byte-comparable, so this is a structural/visual
match, verified by generating a real PDF and reading it back (T20), not a
diff. `_debt_lines`/`LEASE_ASSUMPTION_NOTE` are deliberately duplicated
from financial_analyzer.py for the same reason `Sin` was duplicated in
T11 - they collapse into one copy once T21 deletes the emptied
build_pdf_report().
"""

import pandas as pd
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, Paragraph, Spacer

from fundamental_express.domain.valuation import _peg_assessment
from fundamental_express.reporting.charts import generate_fcf_chart
from fundamental_express.reporting.flowables import CalloutBox
from fundamental_express.reporting.sections import Section
from fundamental_express.reporting.tables import create_reportlab_table
from fundamental_express.reporting.theme import COLORS, FONT_NAME, FONT_BOLD, USABLE_W, _fmt_or_na, pdf_safe

LEASE_ASSUMPTION_NOTE = (
    "Допущение по лизингу: в базовом DCF обязательства по аренде исключены из net debt, "
    "поскольку модель использует FCF после операционных арендных платежей. Это "
    "упрощающее допущение, а не универсальный бухгалтерский факт (выплаты по финансовой "
    "аренде могут классифицироваться иначе) - для сопоставлений, где lease liabilities "
    "рассматриваются как debt-like obligations, используйте альтернативный расчёт с "
    "Total Debt (включая аренду) вместо приведённого net debt."
)

_BODY = dict(fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6)
_CALLOUT_TEXT = dict(fontName=FONT_NAME, fontSize=9, textColor=COLORS["body"], leading=13)


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
        body_style = ParagraphStyle("Body", **_BODY)
        callout_style = ParagraphStyle("CalloutText", **_CALLOUT_TEXT)
        items = [
            Paragraph("<b>Итоговое решение по алгоритму:</b>", body_style),
            Paragraph(pdf_safe(m.scoring.verdict), verdict_style),
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
                "<b>Финансовые риски:</b> Грехов не обнаружено. Финансовые показатели компании находятся в безупречной форме.",
                USABLE_W, COLORS, callout_style, COLORS["success"],
            ))
        return items

    return Section("Экспресс-вердикт и оценка рисков", markdown, flowables)


def _fundamentals_section(m, trading_ccy, ticker):
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
        note = f"\n\n> {m.nonrecurring_note}" if m.nonrecurring_note else ""
        return f"""## 2. Экспресс-анализ финансовых результатов и баланса

Показатели в млн. {trading_ccy}.

{table_rows}{note}"""

    def flowables():
        body_style = ParagraphStyle("Body", **_BODY)
        # PDF space is tighter than markdown - the table windows to the
        # last 4 years, matching build_pdf_report()'s existing behavior.
        last4 = range(len(year_labels) - 4, len(year_labels))
        headers = [f"Показатель (в млн. {trading_ccy})"] + [year_labels[i] for i in last4]
        rows = [
            ["Выручка (Revenue)"] + [f"{m.revenue.iloc[i] / 1e6:,.1f}" for i in last4],
            ["Операционная прибыль (Operating Income)"] + [f"{m.operating_income.iloc[i] / 1e6:,.1f}" for i in last4],
            ["Чистая прибыль (Net Income)"] + [f"{m.net_income.iloc[i] / 1e6:,.1f}" for i in last4],
            ["Разводненная прибыль на акцию (EPS, USD)"] + [f"{m.eps.iloc[i]:.2f}" for i in last4],
            ["Оборотные активы (Current Assets)"] + [f"{m.curr_assets.iloc[i] / 1e6:,.1f}" for i in last4],
            ["Краткосрочные обязательства (Current Liab)"] + [f"{m.curr_liab.iloc[i] / 1e6:,.1f}" for i in last4],
            ["Текущая ликвидность (Current Ratio)"] + [f"{m.curr_ratios.iloc[i]:.2f}" for i in last4],
            ["Акционерный капитал (Shareholders Equity)"] + [f"{m.equity.iloc[i] / 1e6:,.1f}" for i in last4],
            ["Чистый Свободный кэш (Free Cash Flow)"] + [f"{m.fcf.iloc[i] / 1e6:,.1f}" for i in last4],
        ]
        chart_img_path = generate_fcf_chart(year_labels, m.fcf.values, m.proj_years, m.projected_fcfs, ticker)
        flowable_items = [
            Paragraph(
                "Ниже представлена сводная таблица фундаментальных показателей компании за последние 4 отчетных года. "
                "Основной упор сделан на динамику изменения капитала, ликвидности и денежных потоков.",
                body_style,
            ),
            create_reportlab_table(headers, rows, {}, COLORS, col_widths=[190, 70, 70, 70, 70]),
        ]
        if m.nonrecurring_note:
            flowable_items.append(Spacer(1, 6))
            flowable_items.append(Paragraph(m.nonrecurring_note, body_style))
        flowable_items += [
            Spacer(1, 10),
            Image(chart_img_path, width=USABLE_W, height=USABLE_W * 0.4),
        ]
        return flowable_items

    return Section("Экспресс-анализ финансовых результатов и баланса", markdown, flowables)


def _graham_note(m, trading_ccy):
    """V10 (docs/spec/issues/V10-graham-number-reproducible.md): plain text
    for the Graham Number line - справочно, вне основной методики, never
    feeds the sins checklist or the DCF/DDM verdict. Shared between the
    markdown and flowables renderings below."""
    if m.graham_value is None:
        return (
            "Справочно (вне основной методики): Число Грэма недоступно "
            f"(EPS({m.graham_eps_label}) ≤ 0 или tangible BVPS ≤ 0)."
        )
    deviation = (m.graham_value - m.valuation.price) / m.valuation.price * 100 if m.valuation.price else 0.0
    verdict = "недооценена" if deviation > 0 else "переоценена"
    return (
        f"Справочно (вне основной методики): Число Грэма = √(22.5 × EPS({m.graham_eps_label}) × "
        f"tangible BVPS) = {m.graham_value:.2f} {trading_ccy} (EPS={m.graham_eps:.2f}, tangible BVPS="
        f"{m.graham_tangible_bvps:.2f}) — цена {verdict} относительно Числа Грэма на {abs(deviation):.1f}%."
    )


def _valuation_section(m, trading_ccy, price_kind, quote_time_label):
    # V08 (docs/spec/issues/V08-beta-sanity-check.md): flags when beta was
    # replaced by the 1.1 sanity fallback (source value NaN, <-1.0, >3.0),
    # so a reader isn't left trusting a Ke built on a broken beta with no
    # visible sign anything was adjusted.
    beta_note = " (β скорректирована — исходное значение вне разумного диапазона)" if m.valuation.beta_is_fallback else ""
    ke_disclosure = (
        f"Ke = задано инвестором (--required-return) = {m.valuation.cost_of_equity * 100:.2f}%"
        if m.valuation.required_return_used
        else f"Ke = Rf + β×ERP = 4% + {m.valuation.beta:.2f}×5% = {m.valuation.cost_of_equity * 100:.2f}%{beta_note}"
    )
    is_ddm = m.valuation.valuation_model == "DDM"
    # V05 (docs/spec/issues/V05-implied-cost-of-debt.md): distinguishes an
    # implied Kd (from the company's own Interest Expense / Debt) from the
    # flat-fallback Kd, so two tickers that happen to land on the same Kd
    # value aren't shown identically when one arrived there by calculation
    # and the other by fallback.
    kd_source_note = (
        f"{m.cost_of_debt * 100:.2f}% implied по компании (Interest Expense / Долг)"
        if m.cost_of_debt_is_implied
        else f"{m.cost_of_debt * 100:.2f}% fallback методики (нет данных по Interest Expense/Долгу)"
    )

    def markdown():
        if is_ddm:
            return f"""## 3. Оценка справедливой стоимости (Модель DDM)

⚠️ **Внимание:** Применена модель дисконтирования дивидендов (DDM) вместо классического DCF - у компании искажена структура капитала (отрицательный или "перегруженный" долгом акционерный капитал) на фоне стабильной истории дивидендных выплат. Классический FCF-DCF в этом случае занижает стоимость (лизинговые/долговые обязательства искажают WACC).

- {ke_disclosure}
- Темп роста дивидендов (CAGR_div, лог-регрессия по годам, ограничен 2.0%-10.0%): {m.cagr_div * 100:.2f}%
- DPS последнего года (Dividends Paid / Diluted Shares): {m.dps_last:.2f} {trading_ccy}
- Терминальный темп роста (Gordon Growth): {m.terminal_g * 100:.2f}% ({m.terminal_g_label})

**Справедливая стоимость по DDM: {m.valuation.fair_value_share:.2f} {trading_ccy}**
Текущая рыночная цена: {m.valuation.price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) | Статус: **{m.valuation.val_status}**

> {_graham_note(m, trading_ccy)}"""

        # V04: lease-inclusive fair value - always a secondary figure when
        # computable, promoted to headline for a lease-heavy sector (see
        # docs/spec/issues/V04-lease-adjusted-net-debt.md). The two labels
        # below always show whichever number is NOT already the headline
        # "Справедливая стоимость акции" line above, so a reviewer always
        # sees both, never just one.
        lease_incl_line = ""
        lease_headline_suffix = ""
        if m.fair_value_share_incl_leases is not None:
            if m.lease_heavy_sector:
                lease_incl_line = (
                    f"\n- Fair value без учёта аренды как долга (справочно): "
                    f"{m.fair_value_share_excl_leases:.2f} {trading_ccy}"
                )
                lease_headline_suffix = (
                    " (headline - с учётом обязательств по аренде как долга: лизинг-тяжёлый сектор)"
                )
            else:
                lease_incl_line = (
                    f"\n- Fair value с учётом аренды как долга (справочно): "
                    f"{m.fair_value_share_incl_leases:.2f} {trading_ccy}"
                )

        debt_block = "\n".join(f"- {label}: {value}" for label, value in _debt_lines(m, trading_ccy))
        sens_header = "| " + " | ".join(m.sensitivity_headers) + " |"
        sens_sep = "|" + "---|" * len(m.sensitivity_headers)
        sens_rows = "\n".join("| " + " | ".join(r) + " |" for r in m.sensitivity_rows)
        return f"""## 3. Модель дисконтирования денежных потоков (DCF)

- Стоимость собственного капитала: {ke_disclosure}
- Стоимость долга после налога: Kd×(1-T) = {m.cost_of_debt * 100:.2f}%×(1-21%) = {m.cost_of_debt_after_tax * 100:.2f}% (Kd={kd_source_note}; T=21% — фиксированное допущение методики, не эффективная налоговая ставка компании)
- Веса структуры капитала (по рыночной капитализации): E/(D+E) = {m.equity_weight * 100:.1f}%, D/(D+E) = {m.debt_weight * 100:.1f}%
- **WACC:** {m.equity_weight * 100:.1f}%×{m.valuation.cost_of_equity * 100:.2f}% + {m.debt_weight * 100:.1f}%×{m.cost_of_debt_after_tax * 100:.2f}% = **{m.wacc * 100:.2f}%**
- CAGR роста FCF: {m.cagr * 100:.2f}% (лог-регрессия по годам, ограничена 2-15%)
- Терминальный темп роста: {m.terminal_g * 100:.2f}% ({m.terminal_g_label})

{debt_block}

> {LEASE_ASSUMPTION_NOTE}

- Enterprise Value: {m.enterprise_value / 1e9:,.2f} млрд. {trading_ccy}
- Equity Value: {m.equity_value / 1e9:,.2f} млрд. {trading_ccy}{lease_incl_line}

**Справедливая стоимость акции: {m.valuation.fair_value_share:.2f} {trading_ccy}**{lease_headline_suffix}
Последняя доступная рыночная котировка: {m.valuation.price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) | Статус: **{m.valuation.val_status}**

> {_graham_note(m, trading_ccy)}

### Матрица чувствительности (г — рост явного 5-летнего прогноза FCF; терминальный рост фиксирован на {m.terminal_g * 100:.2f}% и используется только в формуле Гордона — условие WACC > g не требуется для этой матрицы)

{sens_header}
{sens_sep}
{sens_rows}"""

    def flowables():
        body_style = ParagraphStyle("Body", **_BODY)
        callout_style = ParagraphStyle("CalloutText", **_CALLOUT_TEXT)
        val_color = COLORS[m.valuation.val_color_key]

        if is_ddm:
            ddm_info_text = (
                f"• <b>Стоимость собственного капитала:</b> {ke_disclosure}<br/>"
                f"• <b>Темп роста дивидендов (CAGR_div, лог-регрессия по годам, ограничен 2.0%-10.0%):</b> {m.cagr_div * 100:.2f}%<br/>"
                f"• <b>DPS последнего года (Dividends Paid / Diluted Shares):</b> {m.dps_last:.2f} {trading_ccy}<br/>"
                f"• <b>Терминальный темп роста (Gordon Growth):</b> {m.terminal_g * 100:.2f}% ({m.terminal_g_label})<br/>"
            )
            val_banner_text = (
                f"<b>СПРАВЕДЛИВАЯ СТОИМОСТЬ ПО DDM: {m.valuation.fair_value_share:.2f} {trading_ccy}</b><br/>"
                f"Текущая рыночная цена: {m.valuation.price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) "
                f"| Статус: <font color='{val_color.hexval()}'><b>{m.valuation.val_status}</b></font>"
            )
            return [
                CalloutBox(ddm_info_text, USABLE_W, COLORS, callout_style, COLORS["accent"]),
                Spacer(1, 8),
                CalloutBox(
                    val_banner_text, USABLE_W, COLORS,
                    ParagraphStyle("ValB", parent=callout_style, fontSize=10, leading=14), val_color,
                ),
                Spacer(1, 6),
                Paragraph(_graham_note(m, trading_ccy), body_style),
            ]

        debt_html = "<br/>".join(f"• <b>{label}:</b> {value}" for label, value in _debt_lines(m, trading_ccy))
        dcf_info_text = (
            f"• <b>Стоимость собственного капитала:</b> {ke_disclosure}<br/>"
            f"• <b>Стоимость долга после налога:</b> Kd×(1-T) = {m.cost_of_debt * 100:.2f}%×(1-21%) = {m.cost_of_debt_after_tax * 100:.2f}% "
            f"(Kd={kd_source_note}; T=21% фиксированное допущение)<br/>"
            f"• <b>Веса структуры капитала:</b> E/(D+E) = {m.equity_weight * 100:.1f}%, D/(D+E) = {m.debt_weight * 100:.1f}% "
            f"(по рыночной капитализации, не по балансовому капиталу — у компаний с отрицательным book equity вес по балансу был бы недействителен)<br/>"
            f"• <b>Итоговый WACC:</b> {m.equity_weight * 100:.1f}%×{m.valuation.cost_of_equity * 100:.2f}% + {m.debt_weight * 100:.1f}%×{m.cost_of_debt_after_tax * 100:.2f}% = <b>{m.wacc * 100:.2f}%</b><br/>"
            f"• <b>Расчетный CAGR роста потока:</b> {m.cagr * 100:.2f}% (лог-регрессия по годам, ограничен консервативной границей)<br/>"
            f"• <b>Терминальный темп роста:</b> {m.terminal_g * 100:.2f}% ({m.terminal_g_label}, пожизненный темп роста компании в постпрогнозный период)<br/>"
            f"{debt_html}<br/>"
            f"• <b>Справедливая оценка акционерного капитала:</b> {m.equity_value / 1e9:,.2f} млрд. {trading_ccy} (Enterprise Value = {m.enterprise_value / 1e9:,.2f} млрд. {trading_ccy})<br/>"
            + (
                f"• <b>Fair value {'без' if m.lease_heavy_sector else 'с'} учётом аренды как долга (справочно):</b> "
                f"{(m.fair_value_share_excl_leases if m.lease_heavy_sector else m.fair_value_share_incl_leases):.2f} {trading_ccy}<br/>"
                if m.fair_value_share_incl_leases is not None else ""
            )
        )
        val_banner_text = (
            f"<b>СПРАВЕДЛИВАЯ СТОИМОСТЬ АКЦИИ: {m.valuation.fair_value_share:.2f} {trading_ccy}</b><br/>"
            f"Последняя доступная рыночная котировка: {m.valuation.price:.2f} {trading_ccy} ({price_kind}, {quote_time_label}) "
            f"| Статус: <font color='{val_color.hexval()}'><b>{m.valuation.val_status}</b></font>"
        )
        return [
            Paragraph(
                "Расчет справедливой стоимости на основе темпов роста FCF и средневзвешенной стоимости капитала (WACC):",
                body_style,
            ),
            CalloutBox(dcf_info_text, USABLE_W, COLORS, callout_style, COLORS["accent"]),
            CalloutBox(LEASE_ASSUMPTION_NOTE, USABLE_W, COLORS, callout_style, COLORS["muted"]),
            Spacer(1, 8),
            CalloutBox(
                val_banner_text, USABLE_W, COLORS,
                ParagraphStyle("ValB", parent=callout_style, fontSize=10, leading=14), val_color,
            ),
            Spacer(1, 6),
            Paragraph(_graham_note(m, trading_ccy), body_style),
            Spacer(1, 10),
            create_reportlab_table(
                ["Прогнозный показатель", "Год 1", "Год 2", "Год 3", "Год 4", "Год 5"],
                [
                    ["Прогнозный FCF (млн. USD)"] + [f"{v / 1e6:,.1f}" for v in m.projected_fcfs],
                    ["Дисконтированный FCF (PV, млн.)"] + [f"{v / 1e6:,.1f}" for v in m.pv_fcfs],
                ],
                {}, COLORS, col_widths=[170, 60, 60, 60, 60, 60],
            ),
            Spacer(1, 12),
            Paragraph(
                "<b>Матрица чувствительности цены акции (WACC vs Рост g):</b>",
                ParagraphStyle("SensT", fontName=FONT_BOLD, fontSize=9.5, textColor=COLORS["heading"], spaceAfter=4),
            ),
            Paragraph(
                "Таблица показывает, как меняется внутренняя стоимость одной акции при изменении ставки дисконтирования "
                "и темпов роста FCF. <b>Важно:</b> g в этой матрице — темп роста явного 5-летнего прогноза FCF, а не "
                "терминальный рост (зафиксирован отдельно на 2.5%, используется только в формуле Гордона).",
                body_style,
            ),
            create_reportlab_table(m.sensitivity_headers, m.sensitivity_rows, {}, COLORS),
        ]

    title = "Оценка справедливой стоимости (Модель DDM)" if is_ddm else "Модель дисконтирования денежных потоков (DCF)"
    return Section(title, markdown, flowables)


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
        body_style = ParagraphStyle("Body", **_BODY)
        callout_style = ParagraphStyle("CalloutText", **_CALLOUT_TEXT)
        outlook_text = (
            f"• <b>Forward P/E:</b> {forward_pe_txt} "
            f"[источник: {forward_outlook['forward_pe_source'] or 'N/A'}]<br/>"
            f"• <b>Ожидаемый рост (консенсус):</b> {growth_txt} "
            f"[источник: {forward_outlook['growth_source'] or 'N/A'}]<br/>"
            f"• <b>PEG Ratio:</b> {peg_txt} — "
            f"<font color='{COLORS[peg_color_key].hexval()}'><b>{peg_label}</b></font> "
            f"[источник: {forward_outlook['peg_source'] or 'N/A'}]<br/>"
        )
        return [
            Paragraph(
                "Раздел носит исключительно информационный характер и не влияет на балл экспресс-чеклиста "
                "из раздела 1 — это форвардный (консенсусный) взгляд, балансирующий DCF-модель, построенную "
                "на экстраполяции исторических 4 лет.",
                body_style,
            ),
            CalloutBox(outlook_text, USABLE_W, COLORS, callout_style, COLORS[peg_color_key]),
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
        callout_style = ParagraphStyle("CalloutText", **_CALLOUT_TEXT)
        catalysts_html = "<br/>".join(catalysts_text.splitlines())
        return [CalloutBox(catalysts_html, USABLE_W, COLORS, callout_style, COLORS["muted"])]

    return Section("Катализаторы и риски", markdown, flowables)


def build_ordinary_sections(m, forward_outlook, catalysts_text, trading_ccy, price_kind, quote_time_label, ticker):
    """Ordered list[Section] for the Ordinary report - the five numbered
    blocks build_markdown_report()/build_pdf_report() assemble inline
    today. Sector-warning-banner handling and the closing "important rule"
    disclaimer stay out of scope here (header/footer-level concerns, not
    numbered sections - see docs/spec/refactor-architecture-spec.md
    Section 5 and reporting/pdf.py)."""
    return [
        _checklist_section(m),
        _fundamentals_section(m, trading_ccy, ticker),
        _valuation_section(m, trading_ccy, price_kind, quote_time_label),
        _forward_outlook_section(forward_outlook),
        _catalysts_section(catalysts_text),
    ]
