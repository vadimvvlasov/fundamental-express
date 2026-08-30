"""Unified markdown renderer (docs/spec/refactor-tasks.md T19,
docs/spec/refactor-architecture-spec.md Section 5).

One `render()` replaces build_markdown_report()/build_bank_markdown_report()/
build_reit_markdown_report() - the three no longer branch on asset class,
they just read different metric fields inside their own T17/T18 sections.
`render()` never branches on asset class either: title/footer are looked
up from `metrics.kind` (Ordinary has none, defaults to "ordinary" - see
domain/metrics.py), and the per-section content comes entirely from the
`sections` list the caller already built via build_ordinary_sections()/
build_bank_sections()/build_reit_sections() (T17/T18).

The sector-warning banner is the one thing that stays a `render()`
parameter rather than section content - it's Ordinary-only, and
transparently absent (empty string) for Bank/REIT, matching
check_sector_suitability()'s current dormant-everywhere behavior.
"""

import os
from datetime import datetime

TITLES = {
    "ordinary": "Фундаментальный анализ & оценка DCF",
    "bank": "Фундаментальный анализ & оценка банка",
    "reit": "Фундаментальный анализ & оценка REIT",
}

FOOTERS = {
    "ordinary": (
        "Фундаментальный анализ отвечает на вопрос «что покупать» — точку входа по времени "
        "нужно определять в связке с техническим анализом."
    ),
    "bank": (
        "У банков отсутствуют Enterprise Value и Net Debt в классическом виде - долговая "
        "нагрузка оценивается через Total Debt / Shareholders Equity.\n"
        "Фундаментальный анализ отвечает на вопрос «что покупать» — точку входа по времени "
        "нужно определять в связке с техническим анализом."
    ),
    "reit": (
        "Классический DCF неприменим к REIT (искажение денежного потока операциями с "
        "недвижимостью) - справедливая стоимость оценивается по методу NAV (Net Asset Value) "
        "на базе NOI и отраслевой ставки капитализации (Cap Rate).\n"
        "Фундаментальный анализ отвечает на вопрос «что покупать» — точку входа по времени "
        "нужно определять в связке с техническим анализом."
    ),
}


def render(ticker, data, metrics, sections, excluded_sector=None, excluded_industry=None):
    """Pure content generation - no file I/O (see write() below).

    `sections` is the ordered list[Section] the caller built for this
    asset class (build_ordinary_sections()/build_bank_sections()/
    build_reit_sections()); every section's .markdown() is joined with
    exactly one blank line, matching the current inline renderers' actual
    spacing (verified byte-for-byte against the golden snapshots).
    """
    kind = getattr(metrics, "kind", "ordinary")
    title = TITLES[kind]
    footer = FOOTERS[kind]

    name = data["name"]
    trading_ccy = data.get("trading_currency", "USD")
    financial_ccy = data.get("financial_currency", "USD")

    sector_warning = (
        f"> ⚠️ **ВНИМАНИЕ (НЕПРИМЕНИМАЯ МЕТОДИКА):** Компания относится к сектору "
        f"**{excluded_sector} ({excluded_industry})**. Экспресс-оценка ликвидности (Current Ratio) и "
        "классический расчет справедливой цены по DCF для данного сектора могут быть некорректны и "
        "давать ложные результаты!\n\n"
        if excluded_sector else ""
    )
    fx_line = (
        f"> Отчётность в {financial_ccy}, конвертирована в {trading_ccy} по курсу "
        f"{data.get('fx_rate', 1.0):.4f}\n\n"
        if financial_ccy != trading_ccy else ""
    )

    header = (
        f"{sector_warning}# {title}: {ticker.upper()}\n\n"
        f"Компания: **{name}** | Цена: **{metrics.valuation.price:.2f} {trading_ccy}** "
        f"({data['price_kind']}, Yahoo Finance, {data['quote_time_label']})\n\n"
        f"{fx_line}"
    )
    body = "\n\n".join(s.markdown() for s in sections)
    return f"{header}{body}\n\n---\n{footer}\n"


def write(ticker, content, output_dir):
    """Writes `content` (render()'s return value) to output_dir, same
    filename pattern every asset class has always used."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    md_filename = os.path.join(output_dir, f"{ticker}_fundamental_report_{date_str}.md")
    with open(md_filename, "w") as f:
        f.write(content)
    return md_filename
