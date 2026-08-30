"""Sin registry tests (docs/spec/refactor-tasks.md T11).

Reproduces every verdict/minor_score combination tests/test_verdict_scoring.py
already covers (that file calls compute_metrics() on synthetic financials;
this one calls domain.sins.score() directly on hand-picked Sin lists using
the same sin ids/weights) - proof the registry's arithmetic matches
today's hand-duplicated critical/minor/threshold blocks before anything
is wired to call it.
"""

import pytest

from fundamental_express.domain.sins import (
    ORDINARY_SIN_REGISTRY,
    ORDINARY_REASONING,
    ORDINARY_MAX_MINOR_SCORE,
    BANK_SIN_REGISTRY,
    BANK_MAX_MINOR_SCORE,
    REIT_SIN_REGISTRY,
    REIT_MAX_MINOR_SCORE,
    fire,
    score,
)


def fire_ordinary(sin_id, message=""):
    return fire(ORDINARY_SIN_REGISTRY, sin_id, message)


def sin_ids(sins):
    return {s.id for s in sins}


def test_max_minor_score_matches_existing_weight_tables():
    # Same three constants asserted by test_verdict_scoring.py /
    # test_bank_analyzer.py / test_reit_analyzer.py against the original
    # MINOR_SIN_WEIGHTS-derived MAX_MINOR_SCORE constants.
    assert ORDINARY_MAX_MINOR_SCORE == pytest.approx(8.1)
    assert BANK_MAX_MINOR_SCORE == pytest.approx(5.1)
    assert REIT_MAX_MINOR_SCORE == pytest.approx(4.3)


def test_zero_sins_is_buy():
    result = score([], ORDINARY_SIN_REGISTRY, ORDINARY_REASONING)
    assert result.sins == []
    assert result.critical_sins == []
    assert result.minor_score == 0
    assert result.verdict_color_key == "success"
    assert "КУПИТЬ" in result.verdict


def test_single_critical_sin_forces_skip_even_with_zero_minor_score():
    sins = [fire_ordinary("fcf_negative", "Сжигание денежных средств.")]
    result = score(sins, ORDINARY_SIN_REGISTRY, ORDINARY_REASONING)
    assert sin_ids(result.critical_sins) == {"fcf_negative"}
    assert result.minor_sins == []
    assert result.minor_score == 0
    assert result.verdict_color_key == "danger"
    assert "ПРОПУСТИТЬ" in result.verdict
    assert "fcf_negative" in result.reasoning


def test_minor_score_exactly_1_0_is_buy_boundary_inclusive():
    sins = [fire_ordinary("equity_declining")]
    result = score(sins, ORDINARY_SIN_REGISTRY, ORDINARY_REASONING)
    assert result.critical_sins == []
    assert sin_ids(result.minor_sins) == {"equity_declining"}
    assert result.minor_score == pytest.approx(1.0)
    assert result.verdict_color_key == "success"
    assert "КУПИТЬ" in result.verdict


def test_minor_score_1_1_is_watch():
    sins = [
        fire_ordinary("gross_margin_declining"),
        fire_ordinary("net_income_declining"),
        fire_ordinary("net_margin_declining"),
    ]
    result = score(sins, ORDINARY_SIN_REGISTRY, ORDINARY_REASONING)
    assert result.minor_score == pytest.approx(1.1)
    assert result.verdict_color_key == "warning"
    assert "НАБЛЮДАТЬ" in result.verdict


def test_minor_score_exactly_2_5_is_watch_boundary_inclusive():
    sins = [
        fire_ordinary("equity_declining"),
        fire_ordinary("fcf_declining"),
        fire_ordinary("cr_declining"),
    ]
    result = score(sins, ORDINARY_SIN_REGISTRY, ORDINARY_REASONING)
    assert result.minor_score == pytest.approx(2.5)
    assert result.verdict_color_key == "warning"
    assert "НАБЛЮДАТЬ" in result.verdict


def test_minor_score_2_6_is_skip():
    sins = [
        fire_ordinary("equity_declining"),
        fire_ordinary("fcf_declining"),
        fire_ordinary("net_income_declining"),
        fire_ordinary("net_margin_declining"),
    ]
    result = score(sins, ORDINARY_SIN_REGISTRY, ORDINARY_REASONING)
    assert result.minor_score == pytest.approx(2.6)
    assert result.verdict_color_key == "danger"
    assert "ПРОПУСТИТЬ" in result.verdict
    assert result.max_minor_score == pytest.approx(8.1)


def test_buyback_bonus_alone_floors_at_zero_not_negative():
    sins = [fire_ordinary("buyback_bonus")]
    result = score(sins, ORDINARY_SIN_REGISTRY, ORDINARY_REASONING)
    assert sin_ids(result.minor_sins) == {"buyback_bonus"}
    assert result.minor_score == 0.0  # max(0.0, -0.5) - never negative
    assert "КУПИТЬ" in result.verdict


def test_buyback_bonus_reduces_a_combined_score():
    sins = [fire_ordinary("equity_declining"), fire_ordinary("buyback_bonus")]
    result = score(sins, ORDINARY_SIN_REGISTRY, ORDINARY_REASONING)
    assert sin_ids(result.minor_sins) == {"equity_declining", "buyback_bonus"}
    assert result.minor_score == pytest.approx(0.5)


def test_technical_bypass_sins_excluded_from_ceiling():
    # Ordinary v3 (docs/spec/step4-ordinary-v3-implementation-spec.md
    # Section 2.1/2.2.1): mutually exclusive with equity_negative/
    # lt_insolvency AND with equity_declining, so folding their weight into
    # the ceiling would overstate a combination that can never occur.
    sins = [fire_ordinary("technical_negative_equity"), fire_ordinary("technical_lt_insolvency")]
    result = score(sins, ORDINARY_SIN_REGISTRY, ORDINARY_REASONING)
    assert result.minor_score == pytest.approx(2.0)
    assert result.max_minor_score == pytest.approx(8.1)  # unchanged despite the two fired sins
