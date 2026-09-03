"""Multi-company comparative report CLI. Moved near-unchanged out of
portfolio_analyzer.py (docs/spec/refactor-tasks.md T22) - its own ReportLab
PDF/Markdown assembly (build_comparative_pdf/build_comparative_markdown) is
out of scope for the Section-model unification (spec Section 1).
"""

import argparse
import re
from datetime import datetime

from analyzers import AnalyzerFactory
from financial_analyzer import (
    COLORS,
    FONT_NAME,
    FONT_BOLD,
    PAGE_SIZE,
    MARGIN,
    PAGE_W,
    PAGE_H,
    USABLE_W,
    SectionDivider,
    CalloutBox,
    create_reportlab_table,
    get_company_data,
    UnsupportedSectorError,
    DataUnavailableError,
)
from fundamental_express.cli.args import required_return_type
from fundamental_express.cli.paths import OUTPUT_DIR
from fundamental_express.domain.best_candidates import select_best_candidates
from fundamental_express.reporting.theme import pdf_safe
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer

TICKER_RE = re.compile(r"^([A-Za-z.\-]+):([0-9]+(?:\.[0-9]+)?)$")


def _sins_label(m):
    """Tier-aware sins label shared by the console table, PDF, and Markdown
    outputs - e.g. '1 крит. / 1.5 из 6.1' instead of a flat 'N/11' count."""
    return f"{len(m.scoring.critical_sins)} крит. / {m.scoring.minor_score:.1f} из {m.scoring.max_minor_score:.1f}"


FORCE_WARNING_FOOTNOTE = (
    "⚠️ — Компания из несовместимого сектора (Финансы/REIT). "
    "Экспресс-метрики и DCF-оценка могут быть некорректны."
)


def _ticker_label(r):
    """Ticker label shared by the console table, PDF, and Markdown outputs -
    flags a --force'd holding in a still-restricted sector so it can't blend
    in with a normal, methodology-valid result (see check_sector_suitability -
    currently never fires, kept for a future restricted sector). Banks and
    REIT are never flagged this way - both have a real, methodology-valid
    engine (BankAnalyzer/ReitAnalyzer), so AnalyzerFactory never sets
    excluded_sector for them. REIT rows instead get a "(REIT)" suffix (spec
    Section 6.2) so they're visually distinguishable in the same table."""
    label = f"{r['ticker']} ⚠️" if r.get("excluded_sector") else r["ticker"]
    if r.get("ok") and getattr(r.get("metrics"), "kind", None) == "reit":
        label = f"{label} (REIT)"
    return label


def _is_bank(m):
    return getattr(m, "kind", None) == "bank"


def _is_reit(m):
    return getattr(m, "kind", None) == "reit"


def _liquidity_label(m):
    """Current Ratio for Ordinary, LTD (Loan-to-Deposit) for banks, P/FFO
    for REIT (spec Section 6.2 - replaces P/E) - Current Ratio is meaningless
    for a bank's balance sheet structure or a REIT's depreciation-distorted
    earnings."""
    if _is_bank(m):
        return "N/A" if m.ltd_ratio is None else f"LTD {m.ltd_ratio * 100:.1f}%"
    if _is_reit(m):
        return "N/A" if m.p_ffo is None else f"P/FFO {m.p_ffo:.1f}x"
    return f"CR {m.current_ratio:.2f}" if m.current_ratio is not None else "N/A"


def _cashflow_label(m):
    """FCF for Ordinary, Net Interest Income (NII) for banks, AFFO Payout
    Ratio for REIT (spec Section 6.2 - replaces Payout) - banks and REITs
    don't generate a classical Free Cash Flow figure."""
    if _is_bank(m):
        nii = m.net_interest_income
        return f"NII {nii.iloc[-1] / 1e6:,.0f}M" if len(nii) else "N/A"
    if _is_reit(m):
        ratio = m.affo_payout_ratio
        if ratio is None:
            return "N/A (no div.)"
        return "Payout ∞" if ratio == float("inf") else f"Payout {ratio * 100:.0f}%"
    fcf = m.fcf
    return f"FCF {fcf.iloc[-1] / 1e6:,.0f}M" if len(fcf) else "N/A"


def _leverage_label(m):
    """Net Debt for Ordinary, Total Debt/Shareholders Equity for banks and
    REIT - neither bank nor REIT has an Enterprise Value/Net Debt figure in
    the classical DCF sense (spec Section 2.2.2 / Step 3 Section 4.2)."""
    if _is_bank(m) or _is_reit(m):
        return "N/A" if m.debt_to_equity is None else f"D/E {m.debt_to_equity:.2f}x"
    return f"ND {m.net_debt / 1e9:,.2f}B"


def _type_label(m):
    """"Тип" column for the Best Candidates table - Bank / a REIT category
    derived from its cap_rate_label (e.g. "Industrial / Logistics REIT",
    "Default REIT" when unmatched, "REIT (explicit cap rate)" for the
    info.capRate case) / "Non-financial" for Ordinary."""
    if _is_bank(m):
        return "Bank"
    if _is_reit(m):
        category = m.cap_rate_label.split(":")[0].split("(")[0].strip()
        if category == "Explicit":
            return "REIT (explicit cap rate)"
        return f"{category} REIT"
    return "Non-financial"


def _best_candidates_data(results):
    """Shared selection + per-row (ticker_label, type, deviation_label,
    minor_score, leverage_label) tuples for the markdown/PDF renderers
    below - see domain/best_candidates.py for the selection rule itself
    (every 0-crit/BUY ticker, no cap, Ordinary/Bank/REIT together in one
    list ranked by |deviation|). The `_type_label()` column is what keeps
    an Ordinary DCF deviation visually distinct from a Bank DDM/ROE-P-B
    one at a glance, since the two aren't the same kind of number (see
    the module docstring in domain/best_candidates.py) - the narrative
    text right after the table spells this out once for the whole table
    instead of per row."""
    selection = select_best_candidates(results)

    def row(r):
        m = r["metrics"]
        ou = m.valuation.over_under_pct
        return (
            _ticker_label(r), _type_label(m), f"{ou:+.1f}%",
            f"{m.scoring.minor_score:.1f}", _leverage_label(m),
        )

    return selection, row


def _best_candidates_narrative(selection):
    """Plain-text (not markdown/HTML) sentences shared by both renderers -
    same content as the manually-written version this replaces, but every
    number pulled live from `selection` instead of typed by hand."""
    lines = []
    if selection["candidates"]:
        lines.append(
            "Критерий отбора: 0 критических грехов + вердикт КУПИТЬ (чек-лист грехов), "
            "все квалифицирующиеся тикеры, отсортированы по модулю отклонения от "
            "DCF/DDM/NAV-модели."
        )
        lines.append(
            "Знак и величина отклонения не сравнимы напрямую между типами: у Ordinary это "
            "классический FCF-DCF (плюс = реально дёшево), у банков — DDM/ROE-P-B "
            "(отрицательное отклонение = цена выше модельной справедливой стоимости, не "
            "\"дёшево\"), у REIT — NAV. Вердикт КУПИТЬ идёт из чек-листа грехов, не из знака "
            "отклонения - тикер может быть формально \"переоценен\" по своей модели и всё "
            "равно КУПИТЬ, если фундаментальные показатели чисты. Смотри колонку «Тип»."
        )
    if selection["best_reit"]:
        r = selection["best_reit"]
        m = r["metrics"]
        payout = (
            "н/д" if m.affo_payout_ratio is None
            else "∞" if m.affo_payout_ratio == float("inf")
            else f"{m.affo_payout_ratio * 100:.0f}%"
        )
        de = "н/д" if m.debt_to_equity is None else f"{m.debt_to_equity:.2f}x"
        lines.append(f"Лучший REIT — {_ticker_label(r)}. Payout {payout}, D/E {de}.")
    if selection["bank_count"] >= 3:
        lines.append(
            "Осторожно: в таблице выше несколько банков. Банковский DCF здесь — "
            "excess-return/DDM модель, чувствительнее к спреду ROE-Ke, чем классический "
            "FCF-DCF - не концентрируй портфель в 5-6 банках разом, диверсифицируй."
        )
    if selection["negative_fair_value"]:
        tickers = ", ".join(_ticker_label(r) for r in selection["negative_fair_value"])
        lines.append(
            f"Красные тикеры с отрицательной DCF fair value ({tickers}) — не баг: net debt "
            "превышает Enterprise Value (тяжёлая долговая нагрузка), формула корректно "
            "выдаёт отрицательное число как сигнал \"не покупать\", а не ошибку расчёта."
        )
    return lines


def parse_holdings(args_list):
    holdings = []
    for item in args_list:
        m = TICKER_RE.match(item)
        if not m:
            raise ValueError(
                f"Bad holding '{item}' - expected TICKER:WEIGHT, e.g. TSM:14"
            )
        holdings.append((m.group(1).upper(), float(m.group(2))))
    return holdings


def analyze_holdings(holdings, retries=5, retry_delay=5, force=False, required_return=None):
    """Fetch + analyze each ticker via AnalyzerFactory. Real data only -
    failures are reported, never silently swapped for mock numbers.

    Routes through the same AnalyzerFactory/OrdinaryAnalyzer/BankAnalyzer/
    ReitAnalyzer hierarchy as the single-ticker path (analyzers.py) - this
    is what keeps this comparative tool computing identical numbers to
    financial_analyzer.py once Bank/REIT get real sector-specific logic in
    Step 2/3 (today, in Step 1, all three routes are behaviorally identical
    anyway - see the spec's decision log for why this is done now rather
    than deferred).

    A Financials/REIT ticker without --force raises UnsupportedSectorError
    straight out of this function (not caught here, unlike
    DataUnavailableError) - a bad sector isn't a per-ticker fetch hiccup to
    skip past, it's a reason to abort the whole run before any more Yahoo
    Finance calls or a comparative report gets built on invalid numbers.
    """
    results = []
    for ticker, weight in holdings:
        print(f"\n=== {ticker} ({weight}%) ===")
        try:
            # One fetch to get `info` for AnalyzerFactory's routing decision.
            # analyzer.data is set directly from this below instead of
            # calling analyzer.fetch_data(), which would otherwise trigger a
            # wasteful second full fetch of the same ticker.
            probe_data = get_company_data(ticker, retries=retries, retry_delay=retry_delay, allow_sample=False)
        except DataUnavailableError as e:
            print(f"  SKIPPED: {e}")
            results.append({"ticker": ticker, "weight": weight, "ok": False, "error": str(e)})
            continue
        args = argparse.Namespace(
            retries=retries, retry_delay=retry_delay, allow_sample=False,
            force=force, required_return=required_return,
        )
        analyzer = AnalyzerFactory.get_analyzer(ticker, args, probe_data.get("info", {}))
        analyzer.data = probe_data
        m = analyzer.calculate_metrics()
        results.append({
            "ticker": ticker,
            "weight": weight,
            "name": probe_data["name"],
            "ok": True,
            "metrics": m,
            "excluded_sector": args.excluded_sector,
            "excluded_industry": args.excluded_industry,
        })
    return results


def print_table(results):
    print("\n" + "=" * 100)
    header = (
        f"{'Тикер':<14}{'Вес':<6}{'Цена':<12}{'DCF fair':<12}{'Откл.':<12}{'Вердикт':<20}{'Грехи':<20}"
        f"{'Ликвидность':<14}{'Ден.поток':<14}{'Долг.нагрузка':<14}"
    )
    print(header)
    print("-" * 100)
    for r in results:
        if not r["ok"]:
            print(f"{r['ticker']:<14}{r['weight']:>4.0f}% {'НЕТ ДАННЫХ (Yahoo)':<50}")
            continue
        m = r["metrics"]
        ou = m.valuation.over_under_pct
        label = "недооценена" if ou > 10 else "переоценена" if ou < -10 else "справедливо"
        print(
            f"{_ticker_label(r):<14}{r['weight']:>4.0f}% "
            f"${m.valuation.price:<10.2f}${m.valuation.fair_value_share:<10.2f}"
            f"{ou:+.1f}% ({label:<12}) "
            f"{m.scoring.verdict:<20}{_sins_label(m):<20}"
            f"{_liquidity_label(m):<14}{_cashflow_label(m):<14}{_leverage_label(m):<14}"
        )
    print("=" * 100)
    if any(r.get("excluded_sector") for r in results):
        print(f"* {FORCE_WARNING_FOOTNOTE}")


def build_comparative_pdf(results, name="Portfolio"):
    date_str = datetime.now().strftime("%Y-%m-%d")
    pdf_path = f"{OUTPUT_DIR}/{name}_Comparative_Report_{date_str}.pdf"
    doc = BaseDocTemplate(
        pdf_path, pagesize=PAGE_SIZE,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 15, bottomMargin=MARGIN,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, USABLE_W,
                   PAGE_H - doc.topMargin - doc.bottomMargin, id="main")

    def on_page(canvas, doc_):
        canvas.saveState()
        canvas.setStrokeColor(COLORS["accent"])
        canvas.setLineWidth(1.2)
        y_rule = PAGE_H - MARGIN + 4
        canvas.line(MARGIN, y_rule, PAGE_W - MARGIN, y_rule)
        canvas.setFont(FONT_BOLD, 8)
        canvas.setFillColor(COLORS["muted"])
        canvas.drawString(MARGIN, y_rule + 4, f"СРАВНИТЕЛЬНЫЙ АНАЛИЗ: {name.upper()}")
        canvas.drawRightString(PAGE_W - MARGIN, y_rule + 4, "Экспресс-грехи + DCF")
        y_footer = MARGIN - 24
        canvas.setStrokeColor(COLORS["bg_alt"])
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, y_footer + 12, PAGE_W - MARGIN, y_footer + 12)
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(COLORS["muted"])
        canvas.drawString(MARGIN, y_footer, "Подготовлено ИИ-помощником фундаментального анализа")
        canvas.drawRightString(PAGE_W - MARGIN, y_footer, f"Страница {doc_.page}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="content", frames=frame, onPage=on_page)])

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("T", fontName=FONT_BOLD, fontSize=20, textColor=COLORS["heading"], leading=24, spaceAfter=8)
    sub_style = ParagraphStyle("S", fontName=FONT_NAME, fontSize=11, textColor=COLORS["muted"], leading=14, spaceAfter=15)
    h1 = ParagraphStyle("H1", fontName=FONT_BOLD, fontSize=12, textColor=COLORS["heading"], leading=15, spaceBefore=12, spaceAfter=6, keepWithNext=True)
    body = ParagraphStyle("B", fontName=FONT_NAME, fontSize=9.5, textColor=COLORS["body"], leading=13.5, spaceAfter=6, alignment=TA_JUSTIFY)
    callout_text = ParagraphStyle("C", fontName=FONT_NAME, fontSize=9, textColor=COLORS["body"], leading=13)

    story = [
        Paragraph(f"СРАВНИТЕЛЬНЫЙ АНАЛИЗ ПОРТФЕЛЯ: {name.upper()}", title_style),
        Paragraph("Методика: экспресс-чеклист «грехов» + DCF (CAPM WACC), real data only", sub_style),
        SectionDivider(USABLE_W, COLORS["accent"]),
        Spacer(1, 10),
        Paragraph("1. Сводная таблица", h1),
    ]

    headers = [
        "Тикер", "Вес", "Цена", "DCF fair value", "Откл. от справ. цены", "Вердикт", "Грехи",
        "Ликвидность (CR/LTD/P-FFO)", "Ден.поток (FCF/NII/Payout)", "Долг.нагрузка (ND/D-E)",
    ]
    rows = []
    failed = []
    for r in results:
        w = f"{r['weight']:g}%"
        if not r["ok"]:
            rows.append([r["ticker"], w, "н/д", "н/д", "нет данных (Yahoo)", "н/д", "н/д", "н/д", "н/д", "н/д"])
            failed.append(r["ticker"])
            continue
        m = r["metrics"]
        ou = m.valuation.over_under_pct
        ou_label = f"{ou:+.1f}% ({'недооценена' if ou > 10 else 'переоценена' if ou < -10 else 'справедливо'})"
        rows.append([
            _ticker_label(r), w, f"${m.valuation.price:,.2f}", f"${m.valuation.fair_value_share:,.2f}",
            ou_label, pdf_safe(m.scoring.verdict), _sins_label(m),
            _liquidity_label(m), _cashflow_label(m), _leverage_label(m),
        ])
    story.append(create_reportlab_table(headers, rows, styles, COLORS, col_widths=[38, 26, 48, 55, 95, 60, 60, 55, 55, 60]))
    story.append(Spacer(1, 10))

    if failed:
        story.append(CalloutBox(
            f"<b>Нет данных:</b> {', '.join(failed)} — Yahoo Finance не отдал данные после нескольких попыток. "
            "Никаких mock-чисел не подставлено; повторите запуск позже.",
            USABLE_W, COLORS, callout_text, COLORS["warning"]))
        story.append(Spacer(1, 8))

    if any(r.get("excluded_sector") for r in results):
        story.append(CalloutBox(FORCE_WARNING_FOOTNOTE, USABLE_W, COLORS, callout_text, COLORS["muted"]))
        story.append(Spacer(1, 8))

    selection, best_row = _best_candidates_data(results)
    if selection["candidates"]:
        story.append(Paragraph("2. Лучшие кандидаты", h1))
        best_headers = ["Тикер", "Тип", "Откл. от DCF", "Грехи", "Долг.нагрузка"]
        best_rows = [list(best_row(r)) for r in selection["candidates"]]
        story.append(create_reportlab_table(best_headers, best_rows, styles, COLORS, col_widths=[45, 90, 60, 45, 80]))
        story.append(Spacer(1, 8))
        for line in _best_candidates_narrative(selection):
            story.append(Paragraph(line, body))
        story.append(Spacer(1, 8))

    story.append(Paragraph("3. Детали по «грехам»", h1))
    for r in results:
        if not r["ok"]:
            continue
        m = r["metrics"]
        if m.scoring.sins:
            text = f"<b>{_ticker_label(r)}</b>: " + "; ".join(s.message for s in m.scoring.sins)
            box_color = COLORS["danger"] if m.scoring.critical_sins else COLORS["warning"]
            story.append(CalloutBox(text, USABLE_W, COLORS, callout_text, box_color))
        else:
            story.append(CalloutBox(f"<b>{_ticker_label(r)}</b>: грехов не обнаружено.", USABLE_W, COLORS, callout_text, COLORS["success"]))
        story.append(Spacer(1, 4))

    doc.build(story)
    print(f"\nSuccess! Comparative report saved to: {pdf_path}")
    return pdf_path


def build_comparative_markdown(results, name="Portfolio"):
    date_str = datetime.now().strftime("%Y-%m-%d")
    md_path = f"{OUTPUT_DIR}/{name}_Comparative_Report_{date_str}.md"
    lines = [
        f"# Сравнительный анализ портфеля: {name}",
        "",
        "Методика: экспресс-чеклист «грехов» + DCF (CAPM WACC), real data only.",
        "",
        "## 1. Сводная таблица",
        "",
        "| Тикер | Вес | Цена | DCF fair value | Откл. от справ. цены | Вердикт | Грехи | "
        "Ликвидность (CR/LTD/P-FFO) | Ден.поток (FCF/NII/Payout) | Долг.нагрузка (ND/D-E) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    failed = []
    for r in results:
        w = f"{r['weight']:g}%"
        if not r["ok"]:
            lines.append(f"| {r['ticker']} | {w} | н/д | н/д | нет данных (Yahoo) | н/д | н/д | н/д | н/д | н/д |")
            failed.append(r["ticker"])
            continue
        m = r["metrics"]
        ou = m.valuation.over_under_pct
        ou_label = f"{ou:+.1f}% ({'недооценена' if ou > 10 else 'переоценена' if ou < -10 else 'справедливо'})"
        lines.append(
            f"| {_ticker_label(r)} | {w} | ${m.valuation.price:,.2f} | ${m.valuation.fair_value_share:,.2f} | "
            f"{ou_label} | {m.scoring.verdict} | {_sins_label(m)} | "
            f"{_liquidity_label(m)} | {_cashflow_label(m)} | {_leverage_label(m)} |"
        )
    lines.append("")

    if failed:
        lines += [
            f"> **Нет данных:** {', '.join(failed)} — Yahoo Finance не отдал данные после нескольких попыток. "
            "Никаких mock-чисел не подставлено; повторите запуск позже.",
            "",
        ]

    if any(r.get("excluded_sector") for r in results):
        lines += [f"> {FORCE_WARNING_FOOTNOTE}", ""]

    selection, best_row = _best_candidates_data(results)
    if selection["candidates"]:
        lines.append("## 2. Лучшие кандидаты")
        lines.append("")
        lines.append("| Тикер | Тип | Откл. от DCF | Грехи | Долг.нагрузка |")
        lines.append("|---|---|---|---|---|")
        for r in selection["candidates"]:
            ticker, type_, dev, sins, lev = best_row(r)
            lines.append(f"| {ticker} | {type_} | {dev} | {sins} | {lev} |")
        lines.append("")
        for line in _best_candidates_narrative(selection):
            lines.append(line)
            lines.append("")

    lines.append("## 3. Детали по «грехам»")
    lines.append("")
    for r in results:
        if not r["ok"]:
            continue
        m = r["metrics"]
        if m.scoring.sins:
            lines.append(f"- **{_ticker_label(r)}**: " + "; ".join(s.message for s in m.scoring.sins))
        else:
            lines.append(f"- **{_ticker_label(r)}**: грехов не обнаружено.")
    lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Success! Markdown comparative report saved to: {md_path}")
    return md_path


def main():
    parser = argparse.ArgumentParser(
        description="Compare multiple companies (express sins-checklist + DCF) - real data only",
        epilog="Example: python portfolio_analyzer.py TSM:14 SAP:13 FICO:12 --name MyPortfolio",
    )
    parser.add_argument(
        "holdings", nargs="+",
        help="TICKER:WEIGHT pairs, e.g. TSM:14 SAP:13 FICO:12 (weights are just labels here, don't need to sum to 100)",
    )
    parser.add_argument("--name", default="Portfolio", help="Report name (used in the PDF filename/title)")
    parser.add_argument("--retries", type=int, default=5, help="Retries per ticker before giving up (default 5)")
    parser.add_argument("--retry-delay", type=int, default=5, help="Seconds to wait between retries (default 5)")
    parser.add_argument(
        "--force", action="store_true",
        help="Принудительно запустить анализ для несовместимых секторов (Финансы/REIT) под ответственность пользователя.",
    )
    parser.add_argument(
        "--required-return", type=required_return_type, default=None,
        help="Персональная требуемая доходность инвестора (0.05-0.25), заменяет CAPM-расчёт Ke для всех holdings.",
    )
    args = parser.parse_args()

    holdings = parse_holdings(args.holdings)
    try:
        results = analyze_holdings(
            holdings, retries=args.retries, retry_delay=args.retry_delay,
            force=args.force, required_return=args.required_return,
        )
    except UnsupportedSectorError as e:
        print(str(e))
        raise SystemExit(1)
    print_table(results)
    build_comparative_pdf(results, name=args.name)
    build_comparative_markdown(results, name=args.name)


if __name__ == "__main__":
    main()
