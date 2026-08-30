# Architecture Spec: Modular Refactor of `fundamental-express`

Status: DRAFT — planning only, no production code touched by this document.
Audience: a coding agent (Claude Code / Cursor / Devin) executing `docs/spec/refactor-tasks.md` against this repo.
Source of truth for current behavior: `financial_analyzer.py`, `analyzers.py`, `portfolio_analyzer.py` as of commit `08289fa` (branch `refactor/modular-architecture`).

---

## 0. Constraints (restated, binding on every task)

- Behavior-preserving. Same CLI flags, same exit codes, same exception types
  (`DataUnavailableError`, `UnsupportedSectorError`), same output filenames.
- Every Russian user-facing string is moved verbatim, never rewritten.
- No new runtime dependencies (`yfinance`/`pandas`/`numpy`/`matplotlib`/`reportlab` only).
- No behavior improvements, no bug fixes, no CLI flag renames. Anything found along the way
  goes in `docs/spec/refactor-found-issues.md`.
- Numerical output does not drift: DCF, WACC clamps, sin weights, verdict thresholds keep
  their exact current values.
- The 87 existing tests are the safety net. A test file may be mechanically updated to match
  a new import path or attribute-vs-dict access pattern, but never to change what it asserts.

---

## 1. Current-state map

Every top-level symbol in `financial_analyzer.py` (3450 lines), grouped by concern, with its
landing spot in the target tree (Section 2).

| Symbol | Concern | Target module |
|---|---|---|
| `SCRIPT_DIR`, `SCRATCH_DIR`, `OUTPUT_DIR` | paths | `cli/paths.py` |
| `Sin` | domain value type | `domain/sins.py` |
| `MINOR_SIN_WEIGHTS`, `BUYBACK_BONUS_WEIGHT`, `MAX_MINOR_SCORE` | ordinary sin registry | `domain/sins.py` |
| `TECHNICAL_NEGATIVE_EQUITY_WEIGHT`, `TECHNICAL_LT_INSOLVENCY_WEIGHT` | ordinary sin registry (v3 bypass) | `domain/sins.py` |
| `COLORS` | theme | `reporting/theme.py` |
| font registration block (`FONT_NAME`/`FONT_BOLD`) | theme | `reporting/theme.py` |
| `PAGE_SIZE`, `MARGIN`, `PAGE_W`, `PAGE_H`, `USABLE_W` | theme/layout | `reporting/theme.py` |
| `escape_xml` | reporting util | `reporting/theme.py` |
| `find_row` | statement parsing | `data/parsing.py` |
| `DataUnavailableError`, `UnsupportedSectorError` | errors | `data/errors.py` |
| `check_sector_suitability` | routing helper (dormant, kept for warning-banner path) | `domain/routing.py` |
| `_fx_rate` | FX bridge | `data/yahoo.py` |
| `_fetch_once` | yahoo client | `data/yahoo.py` |
| `_sample_data` | sample data | `data/sample.py` |
| `get_company_data` | yahoo client orchestration | `data/yahoo.py` |
| `SectionDivider`, `CalloutBox`, `SectorWarningBanner` | PDF flowables | `reporting/flowables.py` |
| `create_reportlab_table` | PDF tables | `reporting/tables.py` |
| `generate_fcf_chart`, `generate_nii_chart`, `generate_ffo_chart` | PDF charts | `reporting/charts.py` |
| `compute_metrics` (614) | ordinary domain engine | split: `domain/ordinary.py` (conditions) + `domain/valuation.py` (DCF/WACC) + `domain/sins.py` (scoring) |
| `BANK_MINOR_SIN_WEIGHTS`, `BANK_BUYBACK_BONUS_WEIGHT`, `BANK_MAX_MINOR_SCORE` | bank sin registry | `domain/sins.py` |
| `_align_statement_years` | statement parsing (bank/REIT) | `data/parsing.py` |
| `compute_bank_metrics` (363) | bank domain engine | split: `domain/bank.py` + `domain/valuation.py` + `domain/sins.py` |
| `REIT_MINOR_SIN_WEIGHTS`, `REIT_BUYBACK_BONUS_WEIGHT`, `REIT_MAX_MINOR_SCORE` | REIT sin registry | `domain/sins.py` |
| `REIT_CAP_RATE_MATRIX`, `REIT_DEFAULT_CAP_RATE*`, `_reit_cap_rate` | REIT valuation input | `domain/valuation.py` |
| `compute_reit_metrics` (285) | REIT domain engine | split: `domain/reit.py` + `domain/valuation.py` + `domain/sins.py` |
| `_EMPTY_FORWARD_OUTLOOK`, `compute_forward_outlook`, `_peg_assessment` | ordinary forward outlook | `domain/valuation.py` |
| `_fmt_or_na` | formatting util shared by renderers | `reporting/theme.py` |
| `CATALYSTS_PLACEHOLDER`, `resolve_catalysts_text` | CLI input helper | `cli/catalysts.py` |
| `required_return_type` | CLI arg validator | `cli/args.py` |
| `LEASE_ASSUMPTION_NOTE`, `_debt_lines` | ordinary report rows | `reporting/sections_ordinary.py` |
| `build_markdown_report` (155) | ordinary markdown | `reporting/markdown.py` + `reporting/sections_ordinary.py` |
| `build_pdf_report` (388) | ordinary orchestration + PDF | split: `analyzers.py` (orchestration) + `reporting/pdf.py` + `reporting/sections_ordinary.py` |
| `_bank_valuation_disclosure`, `_bank_structural_rows` | bank report rows | `reporting/sections_bank.py` |
| `build_bank_markdown_report` | bank markdown | `reporting/markdown.py` + `reporting/sections_bank.py` |
| `build_bank_pdf_report` (193) | bank orchestration + PDF | split: `analyzers.py` + `reporting/pdf.py` + `reporting/sections_bank.py` |
| `_reit_nav_bridge_rows`, `_reit_operating_rows` | REIT report rows | `reporting/sections_reit.py` |
| `build_reit_markdown_report` | REIT markdown | `reporting/markdown.py` + `reporting/sections_reit.py` |
| `build_reit_pdf_report` (183) | REIT orchestration + PDF | split: `analyzers.py` + `reporting/pdf.py` + `reporting/sections_reit.py` |
| `__main__` argparse block | CLI | `cli/single_ticker.py` |

`analyzers.py` (275 lines: `BaseAnalyzer`, `OrdinaryAnalyzer`, `BankAnalyzer`, `ReitAnalyzer`,
`_is_reit`, `AnalyzerFactory`) stays a single module — it's the wiring layer, not a concern
that benefits from splitting. `portfolio_analyzer.py` (384 lines) moves to `cli/portfolio.py`
near-unchanged; it already only imports the public surface (`COLORS`, `get_company_data`,
`AnalyzerFactory`, flowables, errors) and does its own PDF assembly for the comparative
report, which is out of scope for the section-model unification in Section 5.

---

## 2. Target package layout

```
src/fundamental_express/
  data/
    errors.py       # DataUnavailableError, UnsupportedSectorError
    parsing.py       # find_row, _align_statement_years
    sample.py        # _sample_data
    yahoo.py         # _fetch_once, _fx_rate, get_company_data
  domain/
    sins.py          # Sin, per-asset-class weight tables, generic scorer + verdict thresholds
    valuation.py      # CAPM/WACC/DCF, DDM, NAV, ROE-P-B, cap rate matrix, forward outlook
    routing.py        # check_sector_suitability, _is_reit
    metrics.py        # OrdinaryMetrics/BankMetrics/ReitMetrics frozen dataclasses
    ordinary.py        # compute_metrics's condition checks -> OrdinaryMetrics
    bank.py            # compute_bank_metrics's condition checks -> BankMetrics
    reit.py             # compute_reit_metrics's condition checks -> ReitMetrics
  reporting/
    theme.py          # COLORS, fonts, page geometry, escape_xml, _fmt_or_na
    flowables.py       # SectionDivider, CalloutBox, SectorWarningBanner
    tables.py          # create_reportlab_table
    charts.py           # generate_fcf_chart, generate_nii_chart, generate_ffo_chart
    sections.py         # Section protocol + shared rows (debt lines are the only ordinary/bank/REIT overlap)
    sections_ordinary.py
    sections_bank.py
    sections_reit.py
    markdown.py          # one renderer, driven by a per-asset-class Section list
    pdf.py                # one renderer, driven by a per-asset-class Section list
  analyzers.py           # BaseAnalyzer, OrdinaryAnalyzer, BankAnalyzer, ReitAnalyzer, AnalyzerFactory
  cli/
    args.py              # required_return_type
    catalysts.py          # CATALYSTS_PLACEHOLDER, resolve_catalysts_text
    paths.py              # SCRIPT_DIR, SCRATCH_DIR, OUTPUT_DIR
    single_ticker.py       # financial_analyzer.py's __main__ argparse block
    portfolio.py            # portfolio_analyzer.py, moved near-unchanged
financial_analyzer.py     # deleted in the final task; until then, a thin re-export shim
portfolio_analyzer.py     # deleted in the final task; replaced by a `python -m` entry
tests/                     # unchanged paths, imports updated task-by-task
```

Boundary justification (one sentence each):

- `data/` isolates the only code that talks to the network or the filesystem for input, so
  `domain/` and `reporting/` can be exercised with pure in-memory fixtures (DIP: domain and
  reporting depend on the *shape* of `data/`'s output, not on `yfinance` itself).
- `domain/sins.py` centralizes the one piece of logic — weight tables, `max_minor_score`,
  and the ≤1.0/≤2.5 verdict thresholds — that is today hand-duplicated three times with no
  behavioral difference between the copies (SRP: one module owns "how a checklist becomes a
  verdict").
- `domain/{ordinary,bank,reit}.py` stay three separate modules, not one, because the actual
  *conditions* that fire each sin read different statement rows per asset class (NII vs.
  revenue, occupancy vs. gross margin) — collapsing them would recreate the "reimplement a
  bug-for-bug parallel copy" problem this refactor exists to remove (OCP: a fourth asset
  class adds a fourth module, it doesn't edit these three).
- `domain/valuation.py` is separate from the three condition modules because DCF/WACC, DDM,
  NAV and ROE-P-B are valuation *models*, reusable in isolation from any particular checklist,
  and already share the CAPM beta/cost-of-equity plumbing today.
- `domain/metrics.py` holds only dataclass shapes with no behavior, so every other domain
  module and every reporting module can import it without pulling in fetch/compute logic
  (DIP: renderers depend on a data shape, not on the functions that produce it).
- `reporting/theme.py` + `flowables.py` + `tables.py` + `charts.py` are leaf modules with
  zero knowledge of any asset class — exactly the "theme/colors, flowables, charts" pieces
  called out as safe to extract first, because nothing depends on them and they depend on
  nothing but ReportLab/Matplotlib.
- `reporting/sections*.py` isolate *what rows exist* per asset class from `reporting/{markdown,pdf}.py`,
  which own *how a list of sections becomes a document* — this is the seam that lets one
  markdown renderer and one PDF renderer replace six report-builder functions (SRP split of
  "content" from "layout"; OCP: a fourth asset class adds a fourth `sections_*.py`, the two
  renderers don't change).
- `analyzers.py` is the only module allowed to call `data/`, `domain/`, and `reporting/` in
  the same function — it is deliberately the one place layering is allowed to collapse,
  because a CLI-facing orchestration step has to exist somewhere (SRP at the package level:
  every other module is single-concern *because* this one is allowed to not be).
- `cli/` isolates argparse, catalysts-file resolution, and path constants from everything
  importable as a library, so `domain/` and `reporting/` never depend on `sys.argv` (DIP).

---

## 3. Dataclasses replacing the ~50-key metrics dict

Today `compute_metrics` returns a 50-key dict (`financial_analyzer.py:1144-1196`);
`compute_bank_metrics` and `compute_reit_metrics` return their own 30-ish-key dicts with a
large overlapping subset (`sins`/`critical_sins`/`minor_sins`/`minor_score`/`max_minor_score`/
`verdict`/`verdict_color_key`/`reasoning`/`price`/`fair_value_share`/`over_under_pct`/
`val_status`/`val_color_key`/`beta`/`cost_of_equity`/`valuation_model`/`cagr_div`/`dps_last`/
`current_ratio`/`net_margin_pct` — the last two always `None` for bank/REIT today, a smell
worth keeping byte-for-byte since fixing it is out of scope).

```python
# domain/metrics.py
from dataclasses import dataclass, field

@dataclass(frozen=True)
class ScoringResult:
    sins: list[Sin]
    critical_sins: list[Sin]
    minor_sins: list[Sin]
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
    valuation_model: str
    beta: float | None
    cost_of_equity: float
    required_return_used: bool

@dataclass(frozen=True)
class OrdinaryMetrics:
    scoring: ScoringResult
    valuation: ValuationResult
    year_labels: list[str]
    revenue: "pd.Series"
    operating_income: "pd.Series"
    net_income: "pd.Series"
    eps: "pd.Series"
    curr_assets: "pd.Series"
    curr_liab: "pd.Series"
    curr_ratios: "pd.Series"
    equity: "pd.Series"
    fcf: "pd.Series"
    net_margin: "pd.Series"
    wacc: float
    cost_of_debt_after_tax: float
    equity_weight: float
    debt_weight: float
    cagr: float
    proj_years: list[int]
    projected_fcfs: list[float]
    pv_fcfs: list[float]
    enterprise_value: float
    net_debt: float
    net_debt_source: str
    interest_bearing_debt: float
    lease_liabilities: float
    total_debt_incl_leases: float
    cash_balance: float
    equity_value: float
    sensitivity_headers: list[str]
    sensitivity_rows: list[list[str]]
    current_ratio: float
    net_margin_pct: float | None
    cagr_div: float | None
    dps_last: float | None
    debt_to_equity_ratio: float | None

@dataclass(frozen=True)
class BankMetrics:
    scoring: ScoringResult
    valuation: ValuationResult
    # ... nii, provisions, net_loans, loan_loss_allowance, total_deposits,
    # total_borrowings, shareholders_equity, diluted_shares, ltd_ratio,
    # debt_to_equity, bvps, roe (fields named exactly as today's dict keys)

@dataclass(frozen=True)
class ReitMetrics:
    scoring: ScoringResult
    valuation: ValuationResult
    # ... affo, noi, occupancy_rate, affo_payout_ratio, debt_to_equity,
    # cap_rate, cap_rate_label, property_value, nav, ffo_per_share, p_ffo
```

`ScoringResult`/`ValuationResult` are nested, not flattened, because they are exactly the two
things `domain/sins.py` and `domain/valuation.py` each independently produce — a renderer or
a test that only needs the verdict never has to know a bank has 12 other fields.

Every field keeps its current dict key as its attribute name, so the renaming task
(`m["price"]` → `m.valuation.price`, `m["sins"]` → `m.scoring.sins`) is mechanical, not a
redesign. The 87 tests that do `m["key"]` are updated to attribute access in the same task
that introduces the dataclass (Section "renderers" in `refactor-tasks.md`) — assertions
themselves do not change.

---

## 4. Declarative sin registry

### 4.1 What's actually identical across the three asset classes

Verified directly in the current code (`financial_analyzer.py:971-998`, `:1477-1504`,
`:1852-1879`): the scoring and verdict logic is **byte-identical control flow** across
Ordinary/Bank/REIT — only the weight *values* and the Russian reasoning *text* differ.

```python
critical_sins = [s for s in sins if s.tier == "critical"]
minor_sins = [s for s in sins if s.tier == "minor"]
minor_score = max(0.0, sum(s.weight for s in minor_sins))

if critical_sins:            verdict = SKIP;  reasoning = f"... {crit_labels} ..."
elif minor_score <= 1.0:     verdict = BUY
elif minor_score <= 2.5:     verdict = WATCH
else:                        verdict = SKIP;  reasoning = f"... {minor_score:.1f} из {max_minor_score:.1f} ..."
```

The three `*_MINOR_SIN_WEIGHTS` dicts, three `*_BUYBACK_BONUS_WEIGHT` constants (all `-0.5`),
and three `*_MAX_MINOR_SCORE = sum(weights)` are also structurally identical — just three
different tables.

### 4.2 What is NOT identical (and stays per-asset-class)

The *conditions* that decide whether a given sin id fires read different statement rows
(revenue/gross margin vs. NII/provisions vs. AFFO/occupancy) and can't be unified without
inventing a generic "row comparison DSL" that isn't asked for — that's exactly the kind of
speculative abstraction the constraints rule out. Those conditions stay in
`domain/{ordinary,bank,reit}.py` as three plain functions that each yield `(sin_id, **kwargs)`
tuples for the sins that fired.

### 4.3 Registry design

```python
# domain/sins.py
@dataclass(frozen=True)
class SinSpec:
    tier: str            # "critical" | "minor"
    weight: float         # 0.0 for critical
    message: str           # may contain {kwargs} placeholders, filled at fire time

ORDINARY_SIN_REGISTRY: dict[str, SinSpec] = {
    "equity_declining": SinSpec("minor", 1.0, "Падение балансового капитала..."),
    # ... all 11 ordinary sins, weights copied verbatim from MINOR_SIN_WEIGHTS
    "buyback_bonus": SinSpec("minor", -0.5, "Бонус за байбэк: ..."),
}
BANK_SIN_REGISTRY: dict[str, SinSpec] = {...}   # copied verbatim from BANK_MINOR_SIN_WEIGHTS
REIT_SIN_REGISTRY: dict[str, SinSpec] = {...}    # copied verbatim from REIT_MINOR_SIN_WEIGHTS

def fire(registry: dict[str, SinSpec], sin_id: str, **kwargs) -> Sin:
    spec = registry[sin_id]
    return Sin(sin_id, spec.tier, spec.weight, spec.message.format(**kwargs))

def score(sins: list[Sin], registry: dict[str, SinSpec],
          reasoning_templates: "ReasoningTemplates") -> ScoringResult:
    """The one copy of the critical/minor/threshold logic in Section 4.1."""
    ...

MAX_MINOR_SCORE = {
    "ordinary": sum(s.weight for s in ORDINARY_SIN_REGISTRY.values() if s.weight > 0),
    "bank": sum(s.weight for s in BANK_SIN_REGISTRY.values() if s.weight > 0),
    "reit": sum(s.weight for s in REIT_SIN_REGISTRY.values() if s.weight > 0),
}
```

`reasoning_templates` carries the four Russian reasoning strings per asset class (they differ
in wording — "Банк демонстрирует..." vs. "Траст демонстрирует...") so `score()` stays one
function while every user-facing sentence stays byte-identical to today's.

### 4.4 Proof this reproduces current scores

1. Every weight in `ORDINARY_SIN_REGISTRY`/`BANK_SIN_REGISTRY`/`REIT_SIN_REGISTRY` is copied
   verbatim from `MINOR_SIN_WEIGHTS`/`BANK_MINOR_SIN_WEIGHTS`/`REIT_MINOR_SIN_WEIGHTS` — no
   value is recomputed or re-derived.
2. `MAX_MINOR_SCORE["ordinary"] == 8.1` is already asserted by an existing test
   (`financial_analyzer.py:95` docstring reference) and stays a literal equality check against
   the same registry-derived constant.
3. The golden-output harness (Phase 1 / Task T01) diffs a full markdown report — including
   the verdict line and the minor-score line — for one fixture per asset class, byte for
   byte, before and after the registry replaces the hand-written blocks.
4. The threshold constants (`1.0`, `2.5`) and the buyback bonus (`-0.5`) are extracted as
   named constants once (`domain/sins.py`) instead of three times, so there is only one place
   a transcription error could hide, and the harness catches it immediately if there is one.

---

## 5. Markdown/PDF renderers stop duplicating report structure

Today `build_markdown_report`/`build_bank_markdown_report`/`build_reit_markdown_report` and
`build_pdf_report`/`build_bank_pdf_report`/`build_reit_pdf_report` are six independent
functions that each hand-assemble the same skeleton (title → verdict banner → checklist table
→ valuation section → sensitivity/structural rows → disclosures) with the same section order,
just reading different metric fields and different Russian labels.

`reporting/sections.py` defines the shared contract:

```python
@dataclass(frozen=True)
class Section:
    title: str
    markdown: Callable[[], str]           # returns this section's markdown block
    flowables: Callable[[], list]           # returns this section's ReportLab flowables
```

Each `reporting/sections_{ordinary,bank,reit}.py` builds an ordered `list[Section]` from its
asset class's dataclass (Section 3) — e.g. `sections_bank.py` supplies the NII/provisions
checklist table and the LTD structural rows in place of ordinary's gross-margin checklist and
lease disclosure, in the same slot.

`reporting/markdown.py` and `reporting/pdf.py` each become one function that takes
`(ticker, data, metrics, sections: list[Section])` and renders the shared skeleton — title,
verdict banner, per-section loop, footer — never branching on asset class. This is the actual
mechanism by which nine parallel pipelines collapse into three section modules (content) +
two renderers (layout), matching the 3×3 duplication matrix called out in Section 1 of the
brief.

The bank and REIT `build_*_pdf_report`/`build_*_markdown_report` functions are deleted
entirely once their `sections_*.py` counterpart exists; `build_pdf_report`/
`build_markdown_report` (ordinary) are deleted last since the warning-banner path
(`SectorWarningBanner`, `check_sector_suitability`) only exists there today.

---

## 6. Line-count budget

| Module | Current (est.) | Target | Rationale |
|---|---:|---:|---|
| `data/errors.py` | — | 40 | two exception classes, moved verbatim |
| `data/parsing.py` | — | 60 | `find_row` + `_align_statement_years`, moved verbatim |
| `data/sample.py` | — | 60 | `_sample_data`, moved verbatim |
| `data/yahoo.py` | — | 170 | `_fetch_once`/`_fx_rate`/`get_company_data`, moved verbatim |
| **data/ subtotal** | ~330 (embedded in 3450) | **330** | pure move, no dedup available here |
| `domain/sins.py` | ~90 (3 weight tables + 3 duplicated scoring blocks) | 130 | registry adds ~40 lines of structure but removes two of three duplicated scoring blocks |
| `domain/valuation.py` | ~500 (DCF/WACC/DDM/NAV/ROE-P-B/forward outlook, currently interleaved with conditions) | 420 | extracted as-is; shrinks only because it stops sharing lines with condition-checking code |
| `domain/routing.py` | ~40 | 40 | moved verbatim |
| `domain/metrics.py` | 0 (implicit in dict literals) | 160 | new: explicit dataclass fields, no logic |
| `domain/ordinary.py` | ~350 (condition-checking slice of `compute_metrics`) | 300 | same conditions, minus the now-shared scoring/valuation lines |
| `domain/bank.py` | ~220 | 190 | same |
| `domain/reit.py` | ~180 | 160 | same |
| **domain/ subtotal** | ~1380 | **1400** | +20: the dataclass definitions are new lines with no current equivalent; everything else is a lateral move |
| `reporting/theme.py` | ~90 | 90 | moved verbatim |
| `reporting/flowables.py` | ~70 | 70 | moved verbatim |
| `reporting/tables.py` | ~50 | 50 | moved verbatim |
| `reporting/charts.py` | ~110 (3 near-identical chart functions) | 100 | trivial shared-axis-formatting extraction only |
| `reporting/sections.py` | 0 | 40 | new: the `Section` protocol |
| `reporting/sections_ordinary.py` | ~180 (rows slice of `build_pdf_report`/`build_markdown_report`) | 200 | same content, now a data builder instead of inline in two renderers |
| `reporting/sections_bank.py` | ~140 | 150 | same |
| `reporting/sections_reit.py` | ~130 | 140 | same |
| `reporting/markdown.py` | 155+~90+~85 = 330 (three builders) | 140 | one shared skeleton replaces three |
| `reporting/pdf.py` | 388+193+183 = 764 (three builders, minus the ~180+140+130 already counted as sections) | 420 | one shared skeleton over the same section flowables |
| **reporting/ subtotal** | ~1804 | **1300** | this is where the 3×3 duplication actually pays off |
| `analyzers.py` | 275 | 230 | `generate_pdf_report`/`generate_markdown_report` stop re-fetching/re-computing (Problem 3) once orchestration owns fetch→compute→render explicitly |
| `cli/args.py` + `cli/catalysts.py` + `cli/paths.py` | ~60 | 60 | moved verbatim |
| `cli/single_ticker.py` | ~55 | 55 | moved verbatim |
| `cli/portfolio.py` | 384 | 384 | moved near-unchanged; its own PDF assembly is out of scope |
| **cli/ subtotal** | ~499 | **499** | |
| **Total** | **4115** (current 4 files) | **~3820** | ~7% net reduction |

The reduction is modest and concentrated in `reporting/` (1804 → 1300, the actual 3×3
duplication) and `domain/sins.py` (two of three duplicated scoring blocks removed). It is
*not* padded to a round number: `data/`, `cli/`, and most of `domain/` are near-verbatim
moves with no duplication to remove, and the new dataclass/registry/section scaffolding adds
real lines back. A refactor whose target number doesn't visibly trace to the two duplication
sources above should be treated as suspect.

---

## 7. Explicitly out of scope

- New features of any kind.
- Specialized bank/REIT checklists beyond what `compute_bank_metrics`/`compute_reit_metrics`
  already implement today.
- Internationalization (Russian strings are moved, never parameterized for other locales).
- Async I/O.
- Static type-checker adoption (`mypy`/`pyright`) — dataclasses are introduced for shape, not
  as a vehicle to start type-checking the codebase.
- Fixing `current_ratio`/`net_margin_pct` always being `None` on `BankMetrics`/`ReitMetrics`,
  or any other inconsistency found while mapping the current code — logged to
  `docs/spec/refactor-found-issues.md` instead.
