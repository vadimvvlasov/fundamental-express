# Step 1 Implementation Spec: Analyzer Factory Skeleton + Ordinary Checklist v2

Status: FINAL — ready for a coding agent. Supersedes `step1_ordinary_router_spec.md` / `-v2.md` (kept for
audit-trail history; this file is the single source of truth going forward).

Audience: a coding agent implementing directly against the shipped `fundamental-express` codebase
(post-`31d891b`/`5a49140` — two-tier verdict scoring, Forward Outlook, Catalysts, sector guardrail already live).

---

## 0. Scope and non-goals

**In scope for Step 1:**
1. A class-based routing skeleton (`analyzers.py`: `BaseAnalyzer` → `OrdinaryAnalyzer` / `BankAnalyzer` / `ReitAnalyzer`
   + `AnalyzerFactory`) that both `financial_analyzer.py` and `portfolio_analyzer.py` route through.
2. Three new/changed checks in the Ordinary sins checklist: Dilution (new), Buyback bonus (new), and a
   "smart bypass" reclassification of the existing `cr_below_1` critical check.
3. `--required-return` CLI flag (CAPM override) on both entry points.

**Explicitly out of scope (deferred to Step 2 / Step 3):**
- Real bank-specific metrics/checklist/DDM/PB-ROE valuation (`BankAnalyzer` stays a delegating stub).
- Real REIT-specific metrics/checklist/NAV valuation (`ReitAnalyzer` stays a delegating stub).

**Explicit invariant — read this before touching anything:** Step 1 must produce **zero behavior change**
for any ticker that isn't affected by the three checklist changes in §2. `JPM --force` and `O --force` must
render byte-for-byte the same report content as they do today (full Ordinary checklist/DCF + red banner) —
only the code path that produces them changes (via `BankAnalyzer`/`ReitAnalyzer` delegating to
`OrdinaryAnalyzer`), never the output. This is deliberate (see decision log §6) — do not "improve" the stub
behavior beyond what's specified here.

---

## 1. Architecture: thin Adapter, not a rewrite

**Decision (see §6 for the full reasoning this session settled on): Variant B.** `compute_metrics()`,
`get_company_data()`, `build_pdf_report()`, `build_markdown_report()` in `financial_analyzer.py` are **not**
rewritten. They remain the engine. `OrdinaryAnalyzer` is a thin wrapper around them. `BankAnalyzer` and
`ReitAnalyzer` are stubs that, under `--force`, delegate to an internal `OrdinaryAnalyzer` instance —
identical to today's shipped behavior, just re-routed through a class.

### 1.1 New file: `analyzers.py`

```python
from abc import ABC, abstractmethod

from financial_analyzer import (
    get_company_data, compute_metrics, build_pdf_report, build_markdown_report,
    check_sector_suitability, UnsupportedSectorError, DataUnavailableError,
)


class BaseAnalyzer(ABC):
    """Common interface every sector pipeline implements. Note the interface
    has five methods per the original design brief, but Ordinary's five
    methods are thin/no-op where the existing engine already bundles two
    concerns into one call (see OrdinaryAnalyzer docstring) - the interface
    is kept uniform for BankAnalyzer/ReitAnalyzer's real Step 2/3
    implementations, not because Ordinary needs five separate steps today.
    """

    def __init__(self, ticker, args):
        self.ticker = ticker
        self.args = args
        self.data = None
        self.metrics = None

    @abstractmethod
    def fetch_data(self): ...

    @abstractmethod
    def calculate_metrics(self): ...

    @abstractmethod
    def calculate_fair_value(self): ...

    @abstractmethod
    def generate_markdown_report(self): ...

    @abstractmethod
    def generate_pdf_report(self): ...

    def analyze(self):
        """Convenience orchestration used by both financial_analyzer.py's
        __main__ and portfolio_analyzer.py's analyze_holdings() - the only
        method those two callers need to know about. Runs fetch + metrics +
        fair value; report generation is invoked separately by whichever
        caller needs it (portfolio_analyzer.py never builds a per-ticker
        PDF/MD, only the comparative one)."""
        self.fetch_data()
        self.calculate_metrics()
        self.calculate_fair_value()
        return self.metrics


class OrdinaryAnalyzer(BaseAnalyzer):
    """Adapter over the existing function-based engine. calculate_metrics()
    is where compute_metrics() actually runs - it returns one dict that
    already contains both the sins checklist AND the DCF fair-value fields
    (see compute_metrics()'s return dict in financial_analyzer.py). There is
    no second computation to do in calculate_fair_value() for Ordinary; it's
    a pass-through kept only so the class satisfies BaseAnalyzer's interface
    uniformly with Bank/REIT, which WILL do two genuinely separate
    computations in Step 2/3 (checklist vs. DDM/NAV).
    """

    def fetch_data(self):
        retries = getattr(self.args, "retries", 5)
        retry_delay = getattr(self.args, "retry_delay", 5)
        allow_sample = getattr(self.args, "allow_sample", False)
        self.data = get_company_data(
            self.ticker, retries=retries, retry_delay=retry_delay, allow_sample=allow_sample,
        )
        return self.data

    def calculate_metrics(self):
        required_return = getattr(self.args, "required_return", None)
        self.metrics = compute_metrics(self.data, required_return=required_return)
        return self.metrics

    def calculate_fair_value(self):
        return self.metrics  # already computed by calculate_metrics() - see class docstring

    def generate_markdown_report(self):
        forward_outlook = ...  # unchanged from today's build_pdf_report wiring - see §5 for exact call sites
        return build_markdown_report(
            self.ticker, self.data, self.metrics, forward_outlook,
            getattr(self.args, "catalysts_text", None),
            getattr(self.args, "excluded_sector", None), getattr(self.args, "excluded_industry", None),
        )

    def generate_pdf_report(self):
        return build_pdf_report(
            self.ticker,
            retries=getattr(self.args, "retries", 5),
            retry_delay=getattr(self.args, "retry_delay", 5),
            allow_sample=getattr(self.args, "allow_sample", False),
            catalysts_text=getattr(self.args, "catalysts_text", None),
            force=getattr(self.args, "force", False),
        )
```

`generate_pdf_report()` re-runs `build_pdf_report()`, which re-fetches and re-computes internally — this
duplicates work already done by `fetch_data()`/`calculate_metrics()` for the single-ticker CLI path. This is
an accepted, deliberate seam for Step 1 (see §5.1: `financial_analyzer.py`'s `__main__` keeps calling
`build_pdf_report()` directly today; `analyzers.py` exists primarily so `portfolio_analyzer.py` can route
through it — see §5.2). Do not attempt to eliminate the double-fetch in Step 1; that's a `build_pdf_report()`
refactor (splitting fetch from render) explicitly deferred to avoid touching the tested PDF/MD rendering
code in this pass.

### 1.2 `BankAnalyzer` / `ReitAnalyzer` stubs

**Decision (§6): both delegate to `OrdinaryAnalyzer` under `--force`, exactly matching today's shipped
behavior.** This is not a placeholder in the sense of producing degraded output — it's a structural stub:
the class exists and is routed to, but its computation is 100% delegated.

```python
class BankAnalyzer(BaseAnalyzer):
    """Step 1 stub - see Step 2 spec (not yet written) for real NII/DDM/PB-ROE logic.
    check_sector_suitability() (already shipped) is the single source of truth for the
    fail-fast-without---force behavior; this class does not duplicate that check - the
    Factory calls it before ever instantiating this class (see §1.3)."""

    def __init__(self, ticker, args):
        super().__init__(ticker, args)
        self._delegate = OrdinaryAnalyzer(ticker, args)

    def fetch_data(self):
        return self._delegate.fetch_data()

    def calculate_metrics(self):
        self.metrics = self._delegate.calculate_metrics()
        return self.metrics

    def calculate_fair_value(self):
        return self._delegate.calculate_fair_value()

    def generate_markdown_report(self):
        return self._delegate.generate_markdown_report()

    def generate_pdf_report(self):
        return self._delegate.generate_pdf_report()


class ReitAnalyzer(BankAnalyzer):
    """Identical delegation strategy - subclassing BankAnalyzer here is purely to avoid
    duplicating five one-line delegating methods; there is no REIT-specific behavior in
    Step 1. Do not read anything semantic into this inheritance - re-parent it to
    BaseAnalyzer directly in Step 3 once ReitAnalyzer gets real NAV/FFO logic, since at
    that point it shares nothing with BankAnalyzer."""
```

### 1.3 `AnalyzerFactory`

Reuses `check_sector_suitability()` **as-is** (already shipped, already tested) for both the routing
decision and the fail-fast-without-`--force` behavior — do not reimplement sector detection here.

```python
class AnalyzerFactory:
    @staticmethod
    def get_analyzer(ticker, args, info):
        """`info` is the yfinance .info dict for `ticker` - callers must fetch it once
        (e.g. via a lightweight yf.Ticker(ticker).info call, or by reusing `data["info"]`
        after OrdinaryAnalyzer.fetch_data() if sector routing can wait until after fetch -
        see §5 for exactly where each caller gets this from) and pass it in. This function
        does not fetch data itself - it only routes.

        Raises UnsupportedSectorError (unchanged, from financial_analyzer.py) when the
        sector is restricted and args.force is falsy - callers catch it exactly as they
        do today.
        """
        force = getattr(args, "force", False)
        excluded_sector, excluded_industry = check_sector_suitability(ticker, info, force)
        args.excluded_sector = excluded_sector
        args.excluded_industry = excluded_industry
        if excluded_sector is None:
            return OrdinaryAnalyzer(ticker, args)
        sector = info.get("sector") or ""
        if sector == "Financial Services":
            return BankAnalyzer(ticker, args)
        return ReitAnalyzer(ticker, args)
```

Stashing `excluded_sector`/`excluded_industry` onto `args` is a pragmatic way to thread them into
`OrdinaryAnalyzer.generate_markdown_report()` (which needs them for the warning banner, per the already-shipped
`build_markdown_report(..., excluded_sector, excluded_industry)` signature) without changing that function's
signature again. If this feels too implicit, an acceptable alternative is adding `excluded_sector`/
`excluded_industry` as explicit `BaseAnalyzer.__init__` attributes instead of mutating `args` — pick whichever
reads cleaner in the actual PR; both are equivalent in behavior.

**The chicken-and-egg problem this creates:** `check_sector_suitability()` needs `info`, but `info` only
exists after a real fetch (`_fetch_once()` inside `get_company_data()`). See §5 for how each of the two
entry points resolves this without a second network round-trip.

---

## 2. Ordinary checklist v2 (three changes to `compute_metrics()`)

All three changes are **surgical edits** inside the existing `compute_metrics()` function in
`financial_analyzer.py` — do not restructure the function.

### 2.1 New data extraction

Add two new `find_row()` calls near the existing extraction block (alongside `revenue`, `curr_assets`, etc.):

```python
diluted_shares = find_row(df_fin, ["diluted average shares", "basic average shares"], default_val=float("nan"))
current_debt = find_row(df_bal, ["current debt", "short term debt", "short long term debt"], default_val=float("nan"))
```

Both follow the project's existing convention (see `revenue_cost`, `total_liab`): `default_val=float("nan")`,
and every check using them must be **skipped silently** (not treated as a false negative or false positive)
when the row wasn't found in that ticker's statements — same pattern as the existing Gross Margin and LT
Insolvency checks. Apply the FX conversion (`fx_rate`) to `current_debt` alongside the other monetary rows if
`fx_rate != 1.0` (it is a monetary balance-sheet figure, unlike `diluted_shares` which is a share count).

### 2.2 Dilution (new minor sin, weight 1.0) and Buyback bonus (new minor sin, weight -0.5)

```python
if (
    not diluted_shares.isna().any()
    and len(diluted_shares) >= 2
    and diluted_shares.iloc[-2] != 0  # guard div-by-zero; not expected for a traded issuer, but cheap to check
):
    shares_ratio = diluted_shares.iloc[-1] / diluted_shares.iloc[-2]
    if shares_ratio > 1.015:
        sins.append(Sin(
            "dilution", "minor", MINOR_SIN_WEIGHTS["dilution"],
            f"Размытие долей: средневзвешенное число акций выросло с {diluted_shares.iloc[-2]:,.0f} "
            f"до {diluted_shares.iloc[-1]:,.0f} ({(shares_ratio - 1) * 100:.1f}%).",
        ))
    elif shares_ratio < (1 / 1.015):
        sins.append(Sin(
            "buyback_bonus", "minor", BUYBACK_BONUS_WEIGHT,
            f"Бонус за байбэк: число акций сократилось с {diluted_shares.iloc[-2]:,.0f} "
            f"до {diluted_shares.iloc[-1]:,.0f} ({(1 - shares_ratio) * 100:.1f}%).",
        ))
```

`dilution` and `buyback_bonus` are mutually exclusive via `if`/`elif` (a >1.5% move can only be in one
direction). Add to the module-level weight table:

```python
MINOR_SIN_WEIGHTS = {
    # ... all 9 existing entries, unchanged ...
    "dilution": 1.0,
}
BUYBACK_BONUS_WEIGHT = -0.5  # NOT included in MAX_MINOR_SCORE - it's a reduction, not a badness ceiling
MAX_MINOR_SCORE = sum(MINOR_SIN_WEIGHTS.values())  # now 7.1 (was 6.1) - derived, never hardcode
```

**Floor at zero, applied once, after all sins are collected:**

```python
minor_score = max(0.0, sum(s.weight for s in minor_sins))
```

This is the only line that changes in the existing `critical_sins = ...` / `minor_sins = ...` /
`minor_score = ...` block. Verdict thresholds (BUY ≤ 1.0, WATCH ≤ 2.5, SKIP > 2.5) are **unchanged** — they
already work correctly against a floored score.

### 2.3 Smart bypass for `cr_below_1` (reclassifies an existing critical check)

Current code (unchanged critical/minor CR logic being replaced):

```python
if latest_cr < 1.0:
    sins.append(Sin("cr_below_1", "critical", 0.0, ...))
elif (declining and latest_cr < 2.0):
    sins.append(Sin("cr_declining", "minor", 0.5, ...))
```

New three-way branch — bypass condition requires **both** `latest_fcf > 0` and `cash > current_debt`, and
requires `current_debt` to have actually been found (never grant leniency on missing data):

```python
cr_bypass_eligible = (
    latest_cr < 1.0
    and latest_fcf > 0
    and not pd.isna(current_debt.iloc[-1])
    and not pd.isna(cash.iloc[-1])  # cash defaults to a 0.0-filled series via find_row(), never NaN
    and cash.iloc[-1] > current_debt.iloc[-1]  # in practice today, but check explicitly rather than rely on that default
)
if latest_cr < 1.0 and not cr_bypass_eligible:
    sins.append(Sin(
        "cr_below_1", "critical", 0.0,
        f"Критическая ликвидность: коэффициент текущей ликвидности (Current Ratio) ниже 1.0 ({latest_cr:.2f}).",
    ))
elif latest_cr < 1.0 and cr_bypass_eligible:
    sins.append(Sin(
        "cr_below_1_bypassed", "minor", MINOR_SIN_WEIGHTS["cr_below_1_bypassed"],
        f"Ликвидность ниже 1.0 ({latest_cr:.2f}), но не критична: FCF положительный "
        f"({latest_fcf / 1e6:,.0f} млн) и денежные средства ({cash.iloc[-1] / 1e6:,.0f} млн) "
        f"превышают краткосрочный долг ({current_debt.iloc[-1] / 1e6:,.0f} млн).",
    ))
elif len(curr_ratios) >= 2 and curr_ratios.iloc[-1] < curr_ratios.iloc[-2] and latest_cr < 2.0:
    sins.append(Sin("cr_declining", "minor", MINOR_SIN_WEIGHTS["cr_declining"], ...))  # unchanged
```

Add `"cr_below_1_bypassed": 1.0` to `MINOR_SIN_WEIGHTS` (so `MAX_MINOR_SCORE` becomes **8.1** after both
additions — recompute, don't hardcode). `latest_fcf` must be computed before this block if it currently isn't
yet in scope at this point in the function (it's already extracted earlier for the FCF critical check —
reuse the same variable, don't recompute).

This must remain mutually exclusive with `cr_declining` exactly like today's `cr_below_1`/`cr_declining`
split (the whole point of the original fix was no double-counting on the same underlying CR fact) — the
three-way `if`/`elif`/`elif` above guarantees that.

### 2.4 `--required-return` (CAPM override)

`compute_metrics(data, required_return=None)` — new optional parameter, default `None` preserves 100% of
today's behavior.

```python
if required_return is not None:
    cost_of_equity = required_return
else:
    cost_of_equity = rf_rate + beta * erp  # unchanged CAPM formula
```

Everything downstream (WACC blend, DCF, sensitivity matrix) is unchanged — it already consumes
`cost_of_equity` as a plain float, not the CAPM formula's intermediate terms. Add a disclosure line
distinguishing the two paths in both renderers (PDF `dcf_info_text`, Markdown DCF section):

```python
ke_disclosure = (
    f"Ke = задано инвестором (--required-return) = {cost_of_equity * 100:.2f}%"
    if required_return is not None
    else f"Ke = Rf + β×ERP = 4% + {beta:.2f}×5% = {cost_of_equity * 100:.2f}%"
)
```

Wire this into the existing `dcf_info_text`/Markdown f-string in place of the current hardcoded CAPM line —
this is the only renderer change required by `--required-return`.

### 2.5 CLI: `--required-return` validator (fail-fast, catches the percent/decimal footgun)

Add to **both** `financial_analyzer.py` and `portfolio_analyzer.py`'s argparse setup:

```python
def required_return_type(value):
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
            f"Требуемая доходность должна быть в диапазоне 0.05–0.25 (5%–25%). Получено: {fvalue}."
        )
    return fvalue


parser.add_argument(
    "--required-return", type=required_return_type, default=None,
    help="Персональная требуемая доходность инвестора (0.05-0.25), заменяет CAPM-расчёт Ke.",
)
```

`argparse.ArgumentTypeError` is raised during `parse_args()`, i.e. before any network call — satisfies the
fail-fast requirement without extra plumbing. Both `financial_analyzer.py` and `portfolio_analyzer.py`
already `import argparse` at the top of the file (existing code) — no new import needed, just confirm it's
still there when adding `required_return_type()`.

---

## 3. `financial_analyzer.py`'s `compute_metrics()` call site

`build_pdf_report()` already calls `compute_metrics(data)` — update to
`compute_metrics(data, required_return=getattr(args, "required_return", None))`. Since `build_pdf_report()`
doesn't currently take `args` as a parameter (it takes individual kwargs), add a `required_return=None`
kwarg to its signature alongside the existing `catalysts_text`/`force` kwargs, and pass it through from
`__main__` exactly like those two already are.

---

## 4. `portfolio_analyzer.py` sync — route through `AnalyzerFactory`

**Why this matters now, not just in Step 2:** `financial_analyzer.py` and `portfolio_analyzer.py` share
`compute_metrics()` today, which is *why* Step 1's checklist changes apply identically to both without extra
work. That sharing breaks the moment `BankAnalyzer`/`ReitAnalyzer` get real Step 2/3 logic — at that point
`portfolio_analyzer.py` would keep calling generic `compute_metrics()` on a bank ticker forever unless it
already routes through the Factory. Doing this now, while `OrdinaryAnalyzer`/`BankAnalyzer`/`ReitAnalyzer`
are behaviorally identical, is the safe time to make this change (any regression is trivially visible —
output must be byte-identical to today).

Rewrite `analyze_holdings()`:

```python
from analyzers import AnalyzerFactory
from financial_analyzer import get_company_data, DataUnavailableError, UnsupportedSectorError

def analyze_holdings(holdings, retries=5, retry_delay=5, force=False, required_return=None):
    results = []
    for ticker, weight in holdings:
        print(f"\n=== {ticker} ({weight}%) ===")
        args = argparse.Namespace(
            retries=retries, retry_delay=retry_delay, allow_sample=False,
            force=force, required_return=required_return,
        )
        try:
            # One fetch to get `info` for routing (see §1.3's chicken-and-egg note) -
            # get_company_data() is called again inside analyzer.fetch_data(), which is
            # the same double-fetch tradeoff already accepted in §1.1 for the single-
            # ticker path. Do not try to eliminate it in Step 1.
            probe_data = get_company_data(ticker, retries=retries, retry_delay=retry_delay, allow_sample=False)
        except DataUnavailableError as e:
            print(f"  SKIPPED: {e}")
            results.append({"ticker": ticker, "weight": weight, "ok": False, "error": str(e)})
            continue
        analyzer = AnalyzerFactory.get_analyzer(ticker, args, probe_data.get("info", {}))
        m = analyzer.calculate_metrics()  # fetch_data() would re-fetch; reuse probe_data instead - see note below
        results.append({
            "ticker": ticker, "weight": weight, "name": probe_data["name"], "ok": True, "metrics": m,
            "excluded_sector": args.excluded_sector, "excluded_industry": args.excluded_industry,
        })
    return results
```

**Reuse `probe_data` instead of calling `analyzer.fetch_data()`:** since `OrdinaryAnalyzer.fetch_data()`
would otherwise trigger a *second* full fetch of the same ticker (wasteful and slower for a 10-holding
portfolio). The pragmatic fix: set `analyzer.data = probe_data` directly before calling
`calculate_metrics()`, skipping `fetch_data()` entirely on this path:

```python
analyzer = AnalyzerFactory.get_analyzer(ticker, args, probe_data.get("info", {}))
analyzer.data = probe_data
m = analyzer.calculate_metrics()
```

This is a pragmatic deviation from the clean `fetch → calculate → fair_value` orchestration in
`BaseAnalyzer.analyze()`, justified purely by "don't hit Yahoo Finance twice per holding" — leave a comment
in the code explaining why `analyze()` isn't used here.

Add `--force` and `--required-return` to `portfolio_analyzer.py`'s argparse (mirroring §2.5), thread them
into `analyze_holdings(..., force=args.force, required_return=args.required_return)`. Catch
`UnsupportedSectorError` around the `analyze_holdings()` call in `__main__` exactly as today (unchanged —
`check_sector_suitability()` inside the Factory still raises the same exception type for the same
no-`--force` case, aborting the whole run).

The existing `⚠️` ticker-marker logic (`_ticker_label()`, `FORCE_WARNING_FOOTNOTE`) in
`portfolio_analyzer.py` is **unchanged** — it already keys off `r.get("excluded_sector")`, which the
Factory-routed result dict still populates identically.

---

## 5. Report rendering: no changes beyond §2.4's Ke disclosure line

The PDF/Markdown section structure (sins callouts, Forward Outlook, Catalysts, sector banner) is untouched.
New sins (`dilution`, `buyback_bonus`, `cr_below_1_bypassed`) render automatically through the existing
critical/minor `CalloutBox` grouping in both renderers — no template changes needed there, since they iterate
`m["critical_sins"]`/`m["minor_sins"]` generically.

---

## 6. Decision log (context for why, not just what)

- **Iterative delivery, not big-bang** (Ordinary now; Bank in a future Step 2 spec; REIT in a future Step 3
  spec). Reasoning: `yfinance` schema differences per sector are severe enough that parallel development
  risks compounding parsing bugs across three pipelines at once; iterative delivery gets a working, tested
  tool after each step instead of one large untested change.
- **Thin Adapter over full OOP rewrite** (Variant B). Reasoning: the existing engine is tested (10 passing
  tests) and has accumulated many hard-won edge-case fixes (currency bridge, lease-vs-debt separation,
  `find_row` exact-before-partial matching) that a rewrite risks silently regressing. The Factory/class layer
  is added *around* the engine, not instead of it.
- **`BankAnalyzer`/`ReitAnalyzer` delegate to `OrdinaryAnalyzer` under `--force`, unchanged from today's
  shipped behavior** (not a degraded/placeholder report). Reasoning: any user or automation already relying
  on `--force` output today must see zero regression; a stub that quietly returns less information than
  today would be a silent downgrade, not a stub.
- **Dilution weight = 1.0** (not 0.5). Reasoning: share dilution directly and permanently reduces an
  investor's claim on future earnings — economically equivalent to an EPS cut of the same percentage — so it
  belongs with the other "direct business health" 1.0-weight sins (equity/FCF/revenue/operating income),
  not with the "noisier" 0.5/0.3 tier.
- **`--required-return` validation: fail-fast, not clamp.** Reasoning: silently clamping a user's discount
  rate (e.g. a `15` typo instead of `0.15` being clamped to `0.25`) produces a plausible-looking but
  silently-wrong fair value with no indication anything went wrong — worse than an upfront CLI error.
- **`portfolio_analyzer.py` routes through `AnalyzerFactory` starting in Step 1**, even though it's
  behaviorally inert right now. Reasoning: this is the one spot where deferring the change would create a
  guaranteed, easy-to-miss regression the moment Step 2 ships real bank logic.

---

## 7. Test plan

### 7.1 Unit tests (extend `tests/test_verdict_scoring.py`'s `make_data()` fixture)

Add `diluted_shares` and `current_debt` as new overridable rows in the `make_data()` helper (default: flat,
no dilution, `current_debt` comfortably below `cash`).

1. `shares_ratio > 1.015` → `dilution` fires, weight 1.0, `minor_score` includes it.
2. `shares_ratio < 1/1.015` → `buyback_bonus` fires (weight -0.5); combined with e.g. one 1.0-weight sin
   elsewhere → net score `0.5`, never negative even with buyback alone and zero other sins (floor at 0).
3. `latest_cr < 1.0`, `latest_fcf > 0`, `cash > current_debt` → `cr_below_1_bypassed` (minor, 1.0) fires,
   `cr_below_1` (critical) does **not** fire, verdict is NOT automatically SKIP.
4. Same CR/FCF/cash setup but `current_debt` row missing (NaN) → falls back to today's critical `cr_below_1`
   — bypass never granted on missing data.
5. `latest_cr < 1.0`, `latest_fcf <= 0` → bypass not eligible, critical `cr_below_1` fires as before
   (regression: FCF-negative + CR-below-1.0 must still hit the harsher of the two critical checks correctly —
   confirm `fcf_negative` also fires per existing logic, both critical sins present).
6. `required_return_type("0.12")` → `0.12`. `required_return_type("15")` → raises
   `ArgumentTypeError` mentioning `0.150`. `required_return_type("0.5")` → raises (out of range, not the
   percent-guard branch). `required_return_type("0.03")` → raises (below 0.05).
7. `MAX_MINOR_SCORE == 8.1` (regression guard against a hardcoded stale value once both new entries land).
8. All 10 existing tests in `tests/test_verdict_scoring.py` must still pass unmodified — they exercise
   default `make_data()` values where `diluted_shares`/`current_debt` are flat/uninvolved, so none of them
   should be affected by the new checks (verify explicitly rather than assuming).

### 7.2 Live-ticker verification (per user's original test plan)

- `MCD` — standard Ordinary run, confirm Dilution/Buyback don't spuriously fire on a company with fairly
  stable share count, confirm WACC/DCF numbers unchanged from before this change (same CAGR/Ke/WACC math,
  only new sins added).
- `AAPL` — the flagship case for the smart bypass: Apple's real Current Ratio is below 1.0 (confirmed ~0.89
  in earlier live testing this session) with strongly positive FCF and large cash reserves. Confirm
  `cr_below_1_bypassed` fires instead of the critical `cr_below_1`, and check whether this flips Apple's
  overall verdict away from SKIP (it was SKIP solely due to this one critical sin in prior live testing).
- `TSM` — confirm the currency bridge (TWD/USD) still works unchanged, and that `current_debt`/
  `diluted_shares` extraction handles the FX conversion correctly (current_debt gets converted, diluted
  share *count* does not — it's not a monetary figure).
- `JPM --force` / `O --force` — confirm byte-identical output to pre-Step-1 (full Ordinary report + red
  banner), now produced via `BankAnalyzer`/`ReitAnalyzer` → `OrdinaryAnalyzer` delegation instead of the
  direct call. `JPM` / `O` without `--force` must still fail fast with the unchanged error message.
- `portfolio_analyzer.py AAPL:10 MSFT:15 JPM:12 --force` — confirm the comparative table/PDF/MD still show
  the `⚠️` marker and footnote for JPM, and that AAPL's row now reflects the bypassed CR (no longer
  auto-SKIP from that one critical sin, assuming no other critical sin fires for it at test time).
