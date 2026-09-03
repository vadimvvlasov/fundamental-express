"""Frozen dataclasses replacing the ~50/35/31-key untyped dicts returned by
compute_metrics()/compute_bank_metrics()/compute_reit_metrics()
(docs/spec/refactor-tasks.md T10, docs/spec/refactor-architecture-spec.md
Section 3).

Pure shape, no behavior: every field name matches its current dict key
exactly, so wiring these in later (T13-T15) is a mechanical rename
(`m["price"]` -> `m.valuation.price`), not a redesign. Annotations are
postponed (PEP 563) and never introspected at runtime - this is shape
documentation, not a type-checker adoption (out of scope, see architecture
spec Section 7).

`ScoringResult` is byte-identical in shape across all three asset classes
(verified against the current compute_*_metrics() return dicts).
`ValuationResult` is NOT fully uniform: compute_reit_metrics() never
computes valuation_model/cost_of_equity/required_return_used (NAV pricing
uses a Cap Rate, not a CAPM cost of equity or a DCF/DDM model switch), so
those three fields are optional here, unlike the original architecture
spec draft's assumption that they were universal - see the refactor-tasks
T10 execution report for this correction.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoringResult:
    sins: list
    critical_sins: list
    minor_sins: list
    minor_score: float
    max_minor_score: float
    verdict: str
    verdict_color_key: str
    reasoning: str


@dataclass(frozen=True)
class ValuationResult:
    price: float
    fair_value_share: float
    over_under_pct: float
    val_status: str
    val_color_key: str
    beta: float | None
    # Ordinary/Bank only - compute_reit_metrics() never sets these (NAV
    # valuation has no CAPM cost of equity and no DCF/DDM model switch).
    valuation_model: str | None = None
    cost_of_equity: float | None = None
    required_return_used: bool | None = None
    # V08 (docs/spec/issues/V08-beta-sanity-check.md): True when `beta`
    # above is the 1.1 sanity fallback (source beta was NaN, <-1.0, or
    # >3.0), not Yahoo's raw value - lets the Ke disclosure say so.
    beta_is_fallback: bool = False


@dataclass(frozen=True)
class OrdinaryMetrics:
    scoring: ScoringResult
    valuation: ValuationResult
    year_labels: list
    revenue: object  # pd.Series
    operating_income: object  # pd.Series
    net_income: object  # pd.Series
    eps: object  # pd.Series
    curr_assets: object  # pd.Series
    curr_liab: object  # pd.Series
    curr_ratios: object  # pd.Series
    equity: object  # pd.Series
    fcf: object  # pd.Series
    net_margin: object  # pd.Series
    wacc: float
    cost_of_debt_after_tax: float
    equity_weight: float
    debt_weight: float
    cagr: float
    proj_years: list
    projected_fcfs: list
    pv_fcfs: list
    enterprise_value: float
    net_debt: float
    net_debt_source: str
    interest_bearing_debt: float
    lease_liabilities: float
    total_debt_incl_leases: float
    cash_balance: float
    equity_value: float
    sensitivity_headers: list
    sensitivity_rows: list
    current_ratio: float
    net_margin_pct: float | None
    cagr_div: float | None
    dps_last: float | None
    debt_to_equity_ratio: float | None
    nonrecurring_note: str | None = None
    net_debt_incl_leases: float | None = None
    fair_value_share_incl_leases: float | None = None
    fair_value_share_excl_leases: float | None = None
    lease_heavy_sector: bool = False
    cost_of_debt: float | None = None
    cost_of_debt_is_implied: bool = False
    terminal_g: float = 0.025
    terminal_g_label: str = "Default"
    graham_value: float | None = None
    graham_eps: float | None = None
    graham_eps_label: str = "FY"
    graham_tangible_bvps: float | None = None


@dataclass(frozen=True)
class BankMetrics:
    scoring: ScoringResult
    valuation: ValuationResult
    year_labels: list
    interest_income: object  # pd.Series
    interest_expense: object  # pd.Series
    net_interest_income: object  # pd.Series
    commissions_income: object  # pd.Series
    trading_income: object  # pd.Series
    credit_loss_provision: object  # pd.Series
    non_interest_expense: object  # pd.Series
    net_income: object  # pd.Series
    preferred_dividends: object  # pd.Series
    cash_and_equiv: object  # pd.Series
    trading_assets: object  # pd.Series
    htm_securities: object  # pd.Series
    net_loans: object  # pd.Series
    loan_loss_allowance: object  # pd.Series
    total_deposits: object  # pd.Series
    total_borrowings: object  # pd.Series
    shareholders_equity: object  # pd.Series
    diluted_shares: object  # pd.Series
    ltd_ratio: float | None
    debt_to_equity: float | None
    cagr_div: float | None
    dps_last: float | None
    bvps: float | None
    roe: float | None
    current_ratio: None = None
    net_margin_pct: None = None
    kind: str = "bank"
    nonrecurring_note: str | None = None
    terminal_g: float = 0.025
    terminal_g_label: str = "Default"
    graham_value: float | None = None
    graham_eps: float | None = None
    graham_eps_label: str = "FY"
    graham_tangible_bvps: float | None = None


@dataclass(frozen=True)
class ReitMetrics:
    scoring: ScoringResult
    valuation: ValuationResult
    year_labels: list
    d_and_a: object  # pd.Series
    gain_on_sale: object  # pd.Series
    capex: object  # pd.Series
    net_income: object  # pd.Series
    rental_revenue: object  # pd.Series
    property_opex: object  # pd.Series
    re_taxes: object  # pd.Series
    construction_in_progress: object  # pd.Series
    receivables: object  # pd.Series
    cash: object  # pd.Series
    total_liab: object  # pd.Series
    total_debt: object  # pd.Series
    shareholders_equity: object  # pd.Series
    diluted_shares: object  # pd.Series
    dividends_paid: object  # pd.Series
    ffo: object  # pd.Series
    affo: object  # pd.Series
    noi: object  # pd.Series
    occupancy_rate: float | None
    affo_payout_ratio: float | None
    debt_to_equity: float | None
    cap_rate: float
    cap_rate_label: str
    property_value: float
    nav: float
    ffo_per_share: float | None
    p_ffo: float | None
    current_ratio: None = None
    net_margin_pct: None = None
    kind: str = "reit"
    avg_noi: float | None = None
    avg_noi_years: int = 1
