"""Catalysts/risks text resolution. Moved verbatim out of financial_analyzer.py
(docs/spec/refactor-tasks.md T22).
"""

CATALYSTS_PLACEHOLDER = (
    "Катализаторы не указаны — заполните вручную перед принятием решения. "
    "Справедливая стоимость по DCF может не реализовываться рынком годами без триггера переоценки."
)


def resolve_catalysts_text(catalysts=None, catalysts_file=None):
    """Resolve the qualitative catalysts/risks text for report Section 5.

    Catalysts (product launches, regulatory shifts, reputational-crisis
    recovery) aren't fetchable data - they're an analyst's judgment call, so
    this never auto-generates or auto-fetches them. --catalysts and
    --catalysts-file are mutually exclusive - checked here, before any
    network call, so a bad CLI combo fails fast rather than after a slow
    Yahoo Finance round-trip. Neither given -> the mandatory
    methodology-reminder placeholder, never a fabricated catalyst.
    """
    if catalysts and catalysts_file:
        raise SystemExit("--catalysts and --catalysts-file are mutually exclusive")
    if catalysts_file:
        try:
            with open(catalysts_file, encoding="utf-8") as f:
                text = f.read().strip()
        except FileNotFoundError:
            raise SystemExit(f"--catalysts-file not found: {catalysts_file}")
        return text or CATALYSTS_PLACEHOLDER
    if catalysts:
        return catalysts.strip() or CATALYSTS_PLACEHOLDER
    return CATALYSTS_PLACEHOLDER
