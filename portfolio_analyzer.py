import argparse
import re

from financial_analyzer import (
    COLORS,
    FONT_NAME,
    FONT_BOLD,
    PAGE_SIZE,
    MARGIN,
    PAGE_W,
    PAGE_H,
    USABLE_W,
    OUTPUT_DIR,
    MAX_SINS,
    SectionDivider,
    CalloutBox,
    create_reportlab_table,
    get_company_data,
    compute_metrics,
    DataUnavailableError,
)
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer

TICKER_RE = re.compile(r"^([A-Za-z.\-]+):([0-9]+(?:\.[0-9]+)?)$")


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


def analyze_holdings(holdings, retries=5, retry_delay=5):
    """Fetch + analyze each ticker. Real data only - failures are reported,
    never silently swapped for mock numbers."""
    results = []
    for ticker, weight in holdings:
        print(f"\n=== {ticker} ({weight}%) ===")
        try:
            data = get_company_data(ticker, retries=retries, retry_delay=retry_delay, allow_sample=False)
            m = compute_metrics(data)
            results.append({
                "ticker": ticker,
                "weight": weight,
                "name": data["name"],
                "ok": True,
                "metrics": m,
            })
        except DataUnavailableError as e:
            print(f"  SKIPPED: {e}")
            results.append({"ticker": ticker, "weight": weight, "ok": False, "error": str(e)})
    return results


def print_table(results):
    print("\n" + "=" * 100)
    header = f"{'Тикер':<7}{'Вес':<6}{'Цена':<12}{'DCF fair':<12}{'Откл.':<12}{'Вердикт':<20}{'Грехи':<8}"
    print(header)
    print("-" * 100)
    for r in results:
        if not r["ok"]:
            print(f"{r['ticker']:<7}{r['weight']:>4.0f}% {'НЕТ ДАННЫХ (Yahoo)':<50}")
            continue
        m = r["metrics"]
        ou = m["over_under_pct"]
        label = "недооценена" if ou > 10 else "переоценена" if ou < -10 else "справедливо"
        print(
            f"{r['ticker']:<7}{r['weight']:>4.0f}% "
            f"${m['price']:<10.2f}${m['fair_value_share']:<10.2f}"
            f"{ou:+.1f}% ({label:<12}) "
            f"{m['verdict']:<20}{len(m['sins'])}/{MAX_SINS}"
        )
    print("=" * 100)


def build_comparative_pdf(results, name="Portfolio"):
    pdf_path = f"{OUTPUT_DIR}/{name}_Comparative_Report.pdf"
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

    headers = ["Тикер", "Вес", "Цена", "DCF fair value", "Откл. от справ. цены", "Вердикт", "Грехи"]
    rows = []
    failed = []
    for r in results:
        w = f"{r['weight']:g}%"
        if not r["ok"]:
            rows.append([r["ticker"], w, "н/д", "н/д", "нет данных (Yahoo)", "н/д", "н/д"])
            failed.append(r["ticker"])
            continue
        m = r["metrics"]
        ou = m["over_under_pct"]
        ou_label = f"{ou:+.1f}% ({'недооценена' if ou > 10 else 'переоценена' if ou < -10 else 'справедливо'})"
        rows.append([
            r["ticker"], w, f"${m['price']:,.2f}", f"${m['fair_value_share']:,.2f}",
            ou_label, m["verdict"], f"{len(m['sins'])}/{MAX_SINS}",
        ])
    story.append(create_reportlab_table(headers, rows, styles, COLORS, col_widths=[42, 32, 55, 65, 130, 90, 40]))
    story.append(Spacer(1, 10))

    if failed:
        story.append(CalloutBox(
            f"<b>Нет данных:</b> {', '.join(failed)} — Yahoo Finance не отдал данные после нескольких попыток. "
            "Никаких mock-чисел не подставлено; повторите запуск позже.",
            USABLE_W, COLORS, callout_text, COLORS["warning"]))
        story.append(Spacer(1, 8))

    story.append(Paragraph("2. Детали по «грехам»", h1))
    for r in results:
        if not r["ok"]:
            continue
        m = r["metrics"]
        if m["sins"]:
            text = f"<b>{r['ticker']}</b>: " + "; ".join(m["sins"])
            story.append(CalloutBox(text, USABLE_W, COLORS, callout_text, COLORS["danger"]))
        else:
            story.append(CalloutBox(f"<b>{r['ticker']}</b>: грехов не обнаружено.", USABLE_W, COLORS, callout_text, COLORS["success"]))
        story.append(Spacer(1, 4))

    doc.build(story)
    print(f"\nSuccess! Comparative report saved to: {pdf_path}")
    return pdf_path


def build_comparative_markdown(results, name="Portfolio"):
    md_path = f"{OUTPUT_DIR}/{name}_Comparative_Report.md"
    lines = [
        f"# Сравнительный анализ портфеля: {name}",
        "",
        "Методика: экспресс-чеклист «грехов» + DCF (CAPM WACC), real data only.",
        "",
        "## 1. Сводная таблица",
        "",
        "| Тикер | Вес | Цена | DCF fair value | Откл. от справ. цены | Вердикт | Грехи |",
        "|---|---|---|---|---|---|---|",
    ]
    failed = []
    for r in results:
        w = f"{r['weight']:g}%"
        if not r["ok"]:
            lines.append(f"| {r['ticker']} | {w} | н/д | н/д | нет данных (Yahoo) | н/д | н/д |")
            failed.append(r["ticker"])
            continue
        m = r["metrics"]
        ou = m["over_under_pct"]
        ou_label = f"{ou:+.1f}% ({'недооценена' if ou > 10 else 'переоценена' if ou < -10 else 'справедливо'})"
        lines.append(
            f"| {r['ticker']} | {w} | ${m['price']:,.2f} | ${m['fair_value_share']:,.2f} | "
            f"{ou_label} | {m['verdict']} | {len(m['sins'])}/{MAX_SINS} |"
        )
    lines.append("")

    if failed:
        lines += [
            f"> **Нет данных:** {', '.join(failed)} — Yahoo Finance не отдал данные после нескольких попыток. "
            "Никаких mock-чисел не подставлено; повторите запуск позже.",
            "",
        ]

    lines.append("## 2. Детали по «грехам»")
    lines.append("")
    for r in results:
        if not r["ok"]:
            continue
        m = r["metrics"]
        if m["sins"]:
            lines.append(f"- **{r['ticker']}**: " + "; ".join(m["sins"]))
        else:
            lines.append(f"- **{r['ticker']}**: грехов не обнаружено.")
    lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))
    print(f"Success! Markdown comparative report saved to: {md_path}")
    return md_path


if __name__ == "__main__":
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
    args = parser.parse_args()

    holdings = parse_holdings(args.holdings)
    results = analyze_holdings(holdings, retries=args.retries, retry_delay=args.retry_delay)
    print_table(results)
    build_comparative_pdf(results, name=args.name)
    build_comparative_markdown(results, name=args.name)
