"""argparse `type=` validators. Moved verbatim out of financial_analyzer.py
(docs/spec/refactor-tasks.md T22).
"""

import argparse


def required_return_type(value):
    """argparse `type=` for --required-return. Fails fast (during parse_args(),
    before any network call) rather than silently clamping - a clamped
    out-of-range value (e.g. a `15` typo instead of `0.15`) would produce a
    plausible-looking but silently wrong fair value with no indication
    anything went wrong. Shared by financial_analyzer.py and
    portfolio_analyzer.py so the validation behavior never drifts between them.
    """
    try:
        fvalue = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Требуемая доходность должна быть числом. Получено: '{value}'")
    if fvalue > 1.0:
        suggested = fvalue / 100.0
        raise argparse.ArgumentTypeError(
            f"Некорректное значение: {value}. Параметр --required-return должен быть долей от единицы "
            f"(например, 0.15, а не 15). Возможно, вы имели в виду {suggested:.3f}?"
        )
    if not (0.05 <= fvalue <= 0.25):
        raise argparse.ArgumentTypeError(
            f"Требуемая доходность должна быть в диапазоне 0.05-0.25 (5%-25%). Получено: {fvalue}."
        )
    return fvalue
