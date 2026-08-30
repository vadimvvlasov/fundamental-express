"""Declarative sin registry: one generic scorer replacing the three
byte-identical critical/minor/threshold blocks hand-duplicated across
compute_metrics()/compute_bank_metrics()/compute_reit_metrics()
(docs/spec/refactor-tasks.md T11, docs/spec/refactor-architecture-spec.md
Section 4).

Pure addition - not yet called by compute_*_metrics(), and
financial_analyzer.py is untouched this task (its own `class Sin` stays
put; the `Sin` below is a deliberate duplicate until T13-T15 rewire the
three compute_*_metrics() functions onto this registry and collapse the
two into one - see docs/spec/refactor-tasks.md T11's rollback note, which
requires this task to delete cleanly with no other file touched).

Every weight below is copied verbatim from the corresponding
MINOR_SIN_WEIGHTS/BANK_MINOR_SIN_WEIGHTS/REIT_MINOR_SIN_WEIGHTS dict, and
every verdict/reasoning string is copied verbatim from the matching
compute_*_metrics() branch - see the T11 execution report for the
byte-for-byte cross-check.

The verdict and reasoning STRINGS are the only thing that differs by
asset class - the control flow deciding which one applies (critical sin
present -> SKIP; else minor_score <= 1.0 -> BUY; <= 2.5 -> WATCH; else
SKIP) is byte-identical across all three compute_*_metrics() functions,
which is what makes a single score() function correct here.
"""

from dataclasses import dataclass

from fundamental_express.domain.metrics import ScoringResult


@dataclass
class Sin:
    """One fired checklist violation. `weight` is 0.0 for critical sins -
    weight is meaningless there since any single critical hit is decisive."""

    id: str
    tier: str  # "critical" | "minor"
    weight: float
    message: str


@dataclass(frozen=True)
class SinSpec:
    tier: str  # "critical" | "minor"
    weight: float  # 0.0 for critical
    # False for buyback_bonus (a reduction, not a badness ceiling) and the
    # Ordinary v3 technical-bypass sins (technical_negative_equity/
    # technical_lt_insolvency) - each is mutually exclusive with the sin(s)
    # it substitutes for, so folding it into the ceiling would overstate a
    # combination that can never actually occur (same reasoning as the
    # original MINOR_SIN_WEIGHTS/BUYBACK_BONUS_WEIGHT split).
    counts_toward_max: bool = True


@dataclass(frozen=True)
class ReasoningTemplates:
    """The four Russian reasoning strings for one asset class. `critical`
    and `skip` are str.format() templates (crit_labels / minor_score+
    max_minor_score); `buy` and `watch` are static text."""

    critical: str
    buy: str
    watch: str
    skip: str


# Verdict/color strings are byte-identical across all three asset classes -
# only the reasoning text differs.
VERDICT_BUY = "🟢 КУПИТЬ / СИЛЬНЫЙ КАНДИДАТ"
VERDICT_WATCH = "🟡 НАБЛЮДАТЬ / ОГРАНИЧЕННАЯ ДОЛЯ"
VERDICT_SKIP = "🔴 ПРОПУСТИТЬ / ВЫСОКИЙ РИСК"

BUY_THRESHOLD = 1.0
WATCH_THRESHOLD = 2.5


# ── ORDINARY ──────────────────────────────────────────────────────────
ORDINARY_SIN_REGISTRY = {
    # Critical (any single hit forces SKIP, weight is decorative)
    "fcf_negative": SinSpec("critical", 0.0),
    "cr_below_1": SinSpec("critical", 0.0),
    "lt_insolvency": SinSpec("critical", 0.0),
    "equity_negative": SinSpec("critical", 0.0),
    # Minor (weights copied verbatim from MINOR_SIN_WEIGHTS)
    "equity_declining": SinSpec("minor", 1.0),
    "fcf_declining": SinSpec("minor", 1.0),
    "revenue_declining": SinSpec("minor", 1.0),
    "operating_income_declining": SinSpec("minor", 1.0),
    "dilution": SinSpec("minor", 1.0),
    "cr_below_1_bypassed": SinSpec("minor", 1.0),
    "cr_declining": SinSpec("minor", 0.5),
    "gross_margin_declining": SinSpec("minor", 0.5),
    "operating_margin_declining": SinSpec("minor", 0.5),
    "net_income_declining": SinSpec("minor", 0.3),
    "net_margin_declining": SinSpec("minor", 0.3),
    # Excluded from the ceiling (copied verbatim from BUYBACK_BONUS_WEIGHT /
    # TECHNICAL_NEGATIVE_EQUITY_WEIGHT / TECHNICAL_LT_INSOLVENCY_WEIGHT)
    "buyback_bonus": SinSpec("minor", -0.5, counts_toward_max=False),
    "technical_negative_equity": SinSpec("minor", 1.0, counts_toward_max=False),
    "technical_lt_insolvency": SinSpec("minor", 1.0, counts_toward_max=False),
}

ORDINARY_REASONING = ReasoningTemplates(
    critical=(
        "Обнаружен(ы) критический(е) фактор(ы) риска ({crit_labels}) — см. список ниже. "
        "Любой из них по отдельности делает инвестицию рискованной вне зависимости от прочих показателей."
    ),
    buy="Компания демонстрирует эталонную финансовую устойчивость, растущую выручку, отличную маржинальность и растущий свободный денежный поток. Риски минимальны.",
    watch="Отличный сильный бизнес, однако в финансовых трендах присутствуют умеренные погрешности. Рекомендуется покупка только ограниченной долей.",
    skip=(
        "Взвешенный балл второстепенных нарушений составил {minor_score:.1f} из {max_minor_score:.1f} — "
        "см. список ниже. Совокупность этих факторов делает инвестицию рискованной на текущем этапе."
    ),
)


# ── BANK ──────────────────────────────────────────────────────────────
BANK_SIN_REGISTRY = {
    "nii_non_positive": SinSpec("critical", 0.0),
    "equity_negative": SinSpec("critical", 0.0),
    "nii_declining": SinSpec("minor", 1.0),
    "provision_spike": SinSpec("minor", 1.0),
    "dilution": SinSpec("minor", 1.0),
    "ltd_imbalance": SinSpec("minor", 0.5),
    "dead_cash": SinSpec("minor", 0.5),
    "negative_jaws": SinSpec("minor", 0.5),
    "commissions_declining": SinSpec("minor", 0.3),
    "net_income_declining": SinSpec("minor", 0.3),
    "buyback_bonus": SinSpec("minor", -0.5, counts_toward_max=False),
}

BANK_REASONING = ReasoningTemplates(
    critical=(
        "Обнаружен(ы) критический(е) банковский(е) фактор(ы) риска ({crit_labels}). "
        "Любой из них по отдельности делает инвестицию рискованной вне зависимости от прочих показателей."
    ),
    buy="Банк демонстрирует устойчивую динамику процентного дохода, качества кредитного портфеля и структуры фондирования. Риски минимальны.",
    watch="Банк сохраняет жизнеспособную бизнес-модель, однако в динамике процентной маржи, резервов или структуры баланса присутствуют умеренные погрешности.",
    skip=(
        "Взвешенный балл второстепенных банковских нарушений составил {minor_score:.1f} из "
        "{max_minor_score:.1f}. Совокупность этих факторов делает инвестицию рискованной на текущем этапе."
    ),
)


# ── REIT ──────────────────────────────────────────────────────────────
REIT_SIN_REGISTRY = {
    "affo_payout_over_100": SinSpec("critical", 0.0),
    "occupancy_below_80": SinSpec("critical", 0.0),
    "equity_negative": SinSpec("critical", 0.0),
    "affo_declining": SinSpec("minor", 1.0),
    "occupancy_declining": SinSpec("minor", 1.0),
    "dilution": SinSpec("minor", 1.0),
    "high_leverage": SinSpec("minor", 0.5),
    "noi_declining": SinSpec("minor", 0.5),
    "capex_ratio_growth": SinSpec("minor", 0.3),
    "buyback_bonus": SinSpec("minor", -0.5, counts_toward_max=False),
}

REIT_REASONING = ReasoningTemplates(
    critical=(
        "Обнаружен(ы) критический(е) фактор(ы) риска REIT ({crit_labels}). "
        "Любой из них по отдельности делает инвестицию рискованной вне зависимости от прочих показателей."
    ),
    buy="Траст демонстрирует устойчивый рост AFFO/NOI, комфортную заполняемость объектов и разумную долговую нагрузку. Риски минимальны.",
    watch="Портфель недвижимости остаётся жизнеспособным, однако в динамике AFFO, NOI или долговой нагрузки присутствуют умеренные погрешности.",
    skip=(
        "Взвешенный балл второстепенных нарушений REIT составил {minor_score:.1f} из "
        "{max_minor_score:.1f}. Совокупность этих факторов делает инвестицию рискованной на текущем этапе."
    ),
)


def max_minor_score(registry):
    """Derived ceiling: sum of every minor sin's weight that counts toward
    it (excludes buyback_bonus and any technical-bypass substitute sin)."""
    return sum(
        spec.weight
        for spec in registry.values()
        if spec.tier == "minor" and spec.counts_toward_max
    )


ORDINARY_MAX_MINOR_SCORE = max_minor_score(ORDINARY_SIN_REGISTRY)
BANK_MAX_MINOR_SCORE = max_minor_score(BANK_SIN_REGISTRY)
REIT_MAX_MINOR_SCORE = max_minor_score(REIT_SIN_REGISTRY)


def fire(registry, sin_id, message):
    """Build a fired Sin from its registry entry - the caller still builds
    `message` itself (the same f-string it builds today), this just looks
    up tier/weight so there is one place that mapping lives instead of
    three copy-pasted condition blocks each hardcoding its own weight."""
    spec = registry[sin_id]
    return Sin(sin_id, spec.tier, spec.weight, message)


def score(sins, registry, reasoning):
    """The one copy of the critical/minor/threshold logic that today is
    hand-duplicated identically across all three compute_*_metrics()
    functions (see module docstring)."""
    critical_sins = [s for s in sins if s.tier == "critical"]
    minor_sins = [s for s in sins if s.tier == "minor"]
    minor_score_value = max(0.0, sum(s.weight for s in minor_sins))
    ceiling = max_minor_score(registry)

    if critical_sins:
        crit_labels = ", ".join(s.id for s in critical_sins)
        verdict = VERDICT_SKIP
        verdict_color_key = "danger"
        reasoning_text = reasoning.critical.format(crit_labels=crit_labels)
    elif minor_score_value <= BUY_THRESHOLD:
        verdict = VERDICT_BUY
        verdict_color_key = "success"
        reasoning_text = reasoning.buy
    elif minor_score_value <= WATCH_THRESHOLD:
        verdict = VERDICT_WATCH
        verdict_color_key = "warning"
        reasoning_text = reasoning.watch
    else:
        verdict = VERDICT_SKIP
        verdict_color_key = "danger"
        reasoning_text = reasoning.skip.format(minor_score=minor_score_value, max_minor_score=ceiling)

    return ScoringResult(
        sins=sins,
        critical_sins=critical_sins,
        minor_sins=minor_sins,
        minor_score=minor_score_value,
        max_minor_score=ceiling,
        verdict=verdict,
        verdict_color_key=verdict_color_key,
        reasoning=reasoning_text,
    )
