"""Unified PDF renderer (docs/spec/refactor-tasks.md T20).

One `render()` replaces build_pdf_report()/build_bank_pdf_report()/
build_reit_pdf_report()'s document-assembly portion - it never branches
on asset class, it looks up title/subtitle/running-header/closing-warning
text from `metrics.kind` (Ordinary has none, defaults to "ordinary" - see
domain/metrics.py, same lookup pattern as reporting/markdown.py) and loops
over the caller-supplied `sections` list (built via
build_ordinary_sections()/build_bank_sections()/build_reit_sections(),
T17/T18/T20) for the numbered body content.

PDFs were never byte-comparable page to page (see docs/spec/refactor-tasks.md
T01/T19), so unlike markdown.py this has no golden-diff test - it's
verified by generating a real PDF and reading it back (T20's own
acceptance: "generate-and-open, not diff").
"""

import os
from datetime import datetime

from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer

from fundamental_express.reporting.flowables import CalloutBox, SectionDivider, SectorWarningBanner
from fundamental_express.reporting.theme import (
    COLORS, FONT_NAME, FONT_BOLD, MARGIN, PAGE_SIZE, PAGE_W, PAGE_H, USABLE_W, escape_xml,
)

_WARNING_PREFIX = (
    "<b>Важное правило методики экспресс-анализа:</b><br/>"
    "Фундаментальный анализ дает нам ответ на вопрос <b>что именно</b> покупать. Однако для определения "
    "наилучшего момента и цены входа, фундаментальный анализ <b>обязательно должен использоваться в связке с "
    "техническим анализом</b>. Не пытайтесь применять их отдельно!"
)

STRINGS = {
    "ordinary": {
        "doc_title": "ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ &amp; ОЦЕНКА DCF",
        "subtitle_prefix": "Полный отчет по компании",
        "running_header": "ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ И ОЦЕНКА СТОИМОСТИ",
        "success_label": "Comprehensive report",
        "warning_text": (
            _WARNING_PREFIX + " Справедливая стоимость по модели DCF часто "
            "достигается только при возникновении катализаторов рыночного спроса или корпоративных скандалов, "
            "временно занижающих цену."
        ),
    },
    "bank": {
        "doc_title": "ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ БАНКА",
        "subtitle_prefix": "Полный отчет по банку",
        "running_header": "ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ БАНКА",
        "success_label": "Comprehensive bank report",
        "warning_text": (
            _WARNING_PREFIX + "<br/>У банков отсутствуют Enterprise Value и Net Debt в классическом виде - "
            "долговая нагрузка оценивается через Total Debt / Shareholders Equity, а не через "
            "WACC-дисконтирование FCF."
        ),
    },
    "reit": {
        "doc_title": "ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ REIT",
        "subtitle_prefix": "Полный отчет по REIT",
        "running_header": "ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ REIT",
        "success_label": "Comprehensive REIT report",
        "warning_text": (
            _WARNING_PREFIX + "<br/>Классический DCF неприменим к REIT - справедливая стоимость оценивается по "
            "методу NAV на базе NOI и отраслевой ставки капитализации (Cap Rate), а не через "
            "WACC-дисконтирование FCF."
        ),
    },
}


def render(ticker, data, metrics, sections, output_dir, excluded_sector=None, excluded_industry=None):
    """Builds the PDF and writes it to output_dir - there is no pure
    in-memory PDF representation worth returning separately (ReportLab
    writes directly to the path given at BaseDocTemplate construction, the
    same coupling build_pdf_report() always had). Returns the file path.
    """
    kind = getattr(metrics, "kind", "ordinary")
    strings = STRINGS[kind]

    name = data["name"]
    price_kind = data["price_kind"]
    quote_time_label = data["quote_time_label"]
    trading_ccy = data.get("trading_currency", "USD")

    date_str = datetime.now().strftime("%Y-%m-%d")
    pdf_filename = os.path.join(output_dir, f"{ticker}_fundamental_report_{date_str}.pdf")

    doc = BaseDocTemplate(
        pdf_filename, pagesize=PAGE_SIZE,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN + 15, bottomMargin=MARGIN,
    )
    content_frame = Frame(
        doc.leftMargin, doc.bottomMargin, USABLE_W,
        PAGE_H - doc.topMargin - doc.bottomMargin, id="main",
    )

    def on_later_pages(canvas, doc_):
        canvas.saveState()
        canvas.setStrokeColor(COLORS["accent"])
        canvas.setLineWidth(1.2)
        y_rule = PAGE_H - MARGIN + 4
        canvas.line(MARGIN, y_rule, PAGE_W - MARGIN, y_rule)
        canvas.setFont(FONT_BOLD, 8)
        canvas.setFillColor(COLORS["muted"])
        canvas.drawString(MARGIN, y_rule + 4, f"{strings['running_header']}: {ticker.upper()}")
        canvas.drawRightString(PAGE_W - MARGIN, y_rule + 4, f"{name.upper()}")
        y_footer = MARGIN - 24
        canvas.setStrokeColor(COLORS["bg_alt"])
        canvas.setLineWidth(0.4)
        canvas.line(MARGIN, y_footer + 12, PAGE_W - MARGIN, y_footer + 12)
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(COLORS["muted"])
        canvas.drawString(MARGIN, y_footer, "Подготовлено ИИ-помощником фундаментального анализа")
        canvas.drawRightString(PAGE_W - MARGIN, y_footer, f"Страница {doc_.page}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="content", frames=content_frame, onPage=on_later_pages)])

    title_style = ParagraphStyle(
        "DocTitle", fontName=FONT_BOLD, fontSize=20, textColor=COLORS["heading"], leading=24, spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "DocSub", fontName=FONT_NAME, fontSize=11, textColor=COLORS["muted"], leading=14, spaceAfter=15,
    )
    h1_style = ParagraphStyle(
        "H1", fontName=FONT_BOLD, fontSize=12, textColor=COLORS["heading"], leading=15,
        spaceBefore=12, spaceAfter=6, keepWithNext=True,
    )
    callout_text_style = ParagraphStyle(
        "CalloutText", fontName=FONT_NAME, fontSize=9, textColor=COLORS["body"], leading=13,
    )

    story = []

    if excluded_sector:
        sector_warning_style = ParagraphStyle(
            "SectorWarning", fontName=FONT_BOLD, fontSize=10, textColor=COLORS["white"], leading=14,
        )
        sector_warning_text = (
            "⚠ ВНИМАНИЕ (НЕПРИМЕНИМАЯ МЕТОДИКА): Компания относится к сектору "
            f"<b>{escape_xml(excluded_sector)} ({escape_xml(excluded_industry)})</b>. Экспресс-оценка "
            "ликвидности (Current Ratio) и классический расчет справедливой цены по DCF для данного "
            "сектора могут быть некорректны и давать ложные результаты!"
        )
        story.append(SectorWarningBanner(sector_warning_text, USABLE_W, COLORS, sector_warning_style))
        story.append(Spacer(1, 10))

    story.append(Paragraph(f"{strings['doc_title']}: {ticker.upper()}", title_style))
    story.append(Paragraph(
        f"{strings['subtitle_prefix']}: <b>{name}</b> | Цена: <b>{metrics.valuation.price:.2f} {trading_ccy}</b> "
        f"({price_kind}, Yahoo Finance, {quote_time_label})",
        subtitle_style,
    ))
    story.append(SectionDivider(USABLE_W, COLORS["accent"]))
    story.append(Spacer(1, 10))

    for i, section in enumerate(sections, start=1):
        story.append(Paragraph(f"{i}. {section.title}", h1_style))
        story.extend(section.flowables())
        story.append(Spacer(1, 12))

    story.append(CalloutBox(strings["warning_text"], USABLE_W, COLORS, callout_text_style, COLORS["warning"]))

    doc.build(story)
    return pdf_filename
