# Technical Implementation Spec: Fundamental-Express Methodology Upgrade

Status: DRAFT — built incrementally, section by section.
Audience: a coding agent (Claude Code / Cursor / Devin) implementing directly against this repo.
Source of truth for current behavior: `financial_analyzer.py::compute_metrics()` (shared by PDF, Markdown, and `portfolio_analyzer.py`).

---

## Section 1 — Verdict Scoring Engine (Critical/Minor Tiered Sins)

### 1.1 Problem

Current `compute_metrics()` (financial_analyzer.py:566-640) builds `sins` as a flat `list[str]` and derives the verdict purely from `len(sins)`:

```python
if len(sins) == 0: BUY
elif len(sins) <= 3: WATCH
else: SKIP
```

All 11 checks count equally. A single catastrophic issue (FCF burn) is worth exactly as much as a one-year net-margin dip. This is the "математическая жесткость вердиктов" gap in the feedback.

### 1.2 Target model

Two-tier scoring:

- **CRITICAL** (4 checks) — any single hit forces `SKIP`, regardless of everything else.
- **MINOR** (9 checks) — each carries a weight; weights sum to a `minor_score`; score thresholds decide BUY/WATCH/SKIP when no critical hit is present.

#### Critical checks (unchanged trigger conditions, reclassified)

| id | condition | message (ru, unchanged wording) |
|---|---|---|
| `fcf_negative` | `latest_fcf <= 0` | "Сжигание денежных средств: отрицательный Free Cash Flow." |
| `cr_below_1` | `latest_cr < 1.0` | "Критическая ликвидность: коэффициент текущей ликвидности (Current Ratio) ниже 1.0 ({latest_cr:.2f})." |
| `lt_insolvency` | `long_term_assets_adj.iloc[-1] < long_term_liab.iloc[-1]` | unchanged existing message |
| `equity_negative` | `latest_equity <= 0` | "Отрицательный акционерный капитал: обязательств больше, чем реальных активов." |

#### Minor checks (weighted)

| id | condition | weight | message |
|---|---|---|---|
| `equity_declining` | equity trend down (only reached if `equity_negative` didn't fire — mutually exclusive `elif`) | 1.0 | unchanged existing message |
| `fcf_declining` | FCF trend down (only reached if `fcf_negative` didn't fire — mutually exclusive `elif`) | 1.0 | unchanged existing message |
| `revenue_declining` | revenue YoY down | 1.0 | unchanged existing message |
| `operating_income_declining` | operating income YoY down | 1.0 | unchanged existing message |
| `cr_declining` | CR YoY down **and** `1.0 <= latest_cr < 2.0` | 0.5 | unchanged existing message |
| `gross_margin_declining` | gross margin YoY down | 0.5 | unchanged existing message |
| `operating_margin_declining` | operating margin YoY down | 0.5 | unchanged existing message |
| `net_income_declining` | net income YoY down | 0.3 | unchanged existing message |
| `net_margin_declining` | net margin YoY down | 0.3 | unchanged existing message |

Note the `cr_declining` condition change: today `latest_cr < 2.0` alone gates the trend check, which double-fires alongside `cr_below_1` when CR crashes below 1.0. New condition requires `latest_cr >= 1.0` so the critical and minor checks are mutually exclusive on the same underlying fact.

`max_minor_score = 4×1.0 + 3×0.5 + 2×0.3 = 6.1` (compute this as a derived constant, never hardcode — see 1.4).

### 1.3 Verdict thresholds

```
if any critical sin fired:
    verdict = SKIP
elif minor_score <= 1.0:
    verdict = BUY
elif minor_score <= 2.5:
    verdict = WATCH
else:
    verdict = SKIP
```

Rationale for these cutoffs (out of `MAX_MINOR_SCORE = 6.1`): BUY tolerates roughly one 1.0-weight miss or a couple of 0.3/0.5 noise-tier misses — matches the "no company is perfect" point from the source lecture. WATCH covers moderate multi-metric pressure (e.g. revenue + operating margin both down) while the balance sheet itself stays sound. SKIP requires broad, simultaneous deterioration across sales, profitability, and cash flow — not just one bad year in one metric.

### 1.4 Data structures

Replace the flat `sins: list[str]` with a `Sin` record and keep a flat string list only as a derived/legacy view for existing renderers that just need text.

```python
from dataclasses import dataclass, field

@dataclass
class Sin:
    id: str
    tier: str          # "critical" | "minor"
    weight: float       # 0.0 for critical (weight is meaningless there)
    message: str

CRITICAL_SIN_SPECS = {"fcf_negative", "cr_below_1", "lt_insolvency", "equity_negative"}
MINOR_SIN_WEIGHTS = {
    "equity_declining": 1.0,
    "fcf_declining": 1.0,
    "revenue_declining": 1.0,
    "operating_income_declining": 1.0,
    "cr_declining": 0.5,
    "gross_margin_declining": 0.5,
    "operating_margin_declining": 0.5,
    "net_income_declining": 0.3,
    "net_margin_declining": 0.3,
}
MAX_MINOR_SCORE = sum(MINOR_SIN_WEIGHTS.values())  # 6.1 — never hardcode this number elsewhere
```

`compute_metrics()` builds `sins: list[Sin]` instead of `list[str]`. Delete the module-level `MAX_SINS = 11` constant entirely — it has no equivalent in the new model (there is no fixed denominator; "out of N" displays become "score / MAX_MINOR_SCORE" or a tier breakdown, see 1.5).

Returned dict from `compute_metrics()` changes:

```python
{
    ...,
    "sins": sins,                              # list[Sin] — full detail, tier-tagged
    "critical_sins": [s for s in sins if s.tier == "critical"],
    "minor_sins": [s for s in sins if s.tier == "minor"],
    "minor_score": minor_score,                 # float, sum of fired minor weights
    "max_minor_score": MAX_MINOR_SCORE,
    "verdict": verdict,
    "verdict_color_key": verdict_color_key,
    "reasoning": reasoning,
    ...
}
```

### 1.5 Downstream consumers to update

All three call sites currently assume `sins` is `list[str]` and use `MAX_SINS`:

- **`portfolio_analyzer.py`** (imports `MAX_SINS` at line 15; uses `len(m["sins"])}/{MAX_SINS}` at lines 80, 147, 201; joins `"; ".join(m["sins"])` at lines 164-165, 218-219).
  - Replace `f"{len(m['sins'])}/{MAX_SINS}"` with a tier-aware label, e.g. `f"{len(m['critical_sins'])} крит. / {m['minor_score']:.1f} из {m['max_minor_score']:.1f}"`.
  - Replace `"; ".join(m["sins"])` with `"; ".join(s.message for s in m["sins"])`.
- **`financial_analyzer.py::build_markdown_report`** (line 857: `"\n".join(f"- {s}" for s in m["sins"])`).
  - Change to render two sub-lists: critical sins first (bold/flagged), then minor sins with their weight shown, e.g. `f"- [{s.weight:.1f}] {s.message}"`. Exact Markdown formatting is a rendering choice — keep it a plain list grouped under two `**Критические:**` / `**Второстепенные:**` sub-headers rather than one flat bullet list, so a human skimming the `.md` immediately sees why the verdict landed where it did.
- **`financial_analyzer.py::build_pdf_report`** (sins CalloutBox around lines 1081-1093, currently `f"• {escape_xml(s)}"` over strings).
  - Same grouping as Markdown: two callout boxes (or one box with two labeled sub-sections) — critical in `COLORS["danger"]`, minor in `COLORS["warning"]`. Show `minor_score / max_minor_score` next to the minor heading.

### 1.6 Test cases (add to a new `test_verdict_scoring.py` or equivalent; no test suite currently exists in the repo — confirm with `ls tests/` before assuming one does)

Construct synthetic `data` dicts (reuse the `_sample_data()` shape) or call `compute_metrics()` directly with hand-built DataFrames covering:

1. Zero sins → `verdict == BUY`, `minor_score == 0`.
2. One critical sin only (e.g. `fcf_negative`), zero minor → `verdict == SKIP` (critical always wins, even with a perfect minor score).
3. Minor sins summing to exactly `1.0` → `verdict == BUY` (boundary inclusive).
4. Minor sins summing to `1.1` → `verdict == WATCH`.
5. Minor sins summing to exactly `2.5` → `verdict == WATCH` (boundary inclusive).
6. Minor sins summing to `2.6` → `verdict == SKIP`.
7. `latest_cr == 0.9` (below 1.0) with declining trend → only `cr_below_1` fires, `cr_declining` must NOT also fire (mutual-exclusivity regression test for the double-count bug being fixed).
8. `latest_cr == 1.5` declining from `1.8` → only `cr_declining` (minor, 0.5) fires, not critical.
9. `latest_cr == 2.5` declining from `3.0` → no sin fires at all (existing "healthy decline" carve-out, must still hold).

---

---

## Section 2 — Forward-Looking Outlook Block

### 2.1 Problem

DCF (financial_analyzer.py:642-746) extrapolates purely from trailing 4-year FCF CAGR. Feedback wants a forward-consensus counterweight (Forward P/E, PEG, analyst EPS/revenue growth) plus a qualitative catalysts section, since an undervalued-by-DCF stock can stay undervalued for years absent a re-rating trigger.

This is a new, self-contained **"Forward & Consensus Outlook"** report section. It does not change the DCF math from Section 1 or any existing section — it's additive context sitting alongside it.

### 2.2 Data source and fallback engine

Source: `yfinance`'s `ticker.info` dict — already the library in use, no new dependency. Chosen over `.earnings_estimate`/`.growth_estimates` because `.info` is `yfinance`'s primary, most-maintained surface; the newer structured endpoints scrape Yahoo's web tables directly and break more often on Yahoo's markup changes.

`.info` fields (`forwardPE`, `pegRatio`, `earningsGrowth`, `revenueGrowth`) are frequently `None` for a given ticker. Implement a fallback chain — each fallback also records *which* source actually produced the number, since the report must label it (never present a proxy as if it were the real consensus figure):

```python
def compute_forward_outlook(info: dict, trailing_pe: float | None, historical_fcf_cagr: float) -> dict:
    """Forward P/E, consensus growth, and PEG with an explicit fallback chain.
    Every value that isn't the primary Yahoo consensus field is labeled with
    its actual source so the report never implies a number is analyst
    consensus when it's really a proxy.
    """
    forward_pe = info.get("forwardPE")
    forward_pe_source = "Yahoo Finance (forwardPE)"
    if not forward_pe or forward_pe <= 0:
        forward_pe = trailing_pe
        forward_pe_source = "Trailing P/E (форвардный недоступен, консервативный прокси)"

    growth_rate = info.get("earningsGrowth")
    growth_source = "Analyst Est. (earningsGrowth)"
    if not growth_rate:
        growth_rate = info.get("revenueGrowth")
        growth_source = "Analyst Est. (revenueGrowth, EPS growth недоступен)"
    if not growth_rate:
        growth_rate = historical_fcf_cagr
        growth_source = "Historical FCF Proxy (консенсус недоступен, взят исторический CAGR FCF из DCF)"

    peg_ratio = info.get("pegRatio")
    peg_source = "Yahoo Finance (pegRatio)"
    if (not peg_ratio or peg_ratio <= 0) and forward_pe and growth_rate and growth_rate > 0:
        growth_pct = growth_rate * 100 if growth_rate < 1.0 else growth_rate
        peg_ratio = forward_pe / growth_pct if growth_pct else None
        peg_source = "Расчётный (Forward P/E ÷ Expected Growth %, Yahoo PEG недоступен)"
    elif peg_ratio and peg_ratio <= 0:
        peg_ratio, peg_source = None, None  # negative/zero PEG is not meaningful, show N/A

    return {
        "forward_pe": forward_pe,
        "forward_pe_source": forward_pe_source if forward_pe else None,
        "growth_rate": growth_rate,
        "growth_source": growth_source if growth_rate else None,
        "peg_ratio": peg_ratio,
        "peg_source": peg_source,
    }
```

Known limitation to document inline (comment, not a fix): the `growth_rate < 1.0` heuristic to detect "already a fraction vs already a percentage" misreads a >100%-YoY growth fraction (e.g. `1.5` meaning +150%) as an already-converted percentage. Accept this — it mirrors the existing codebase's tolerance for imperfect heuristics on noisy provider data (see `find_row`'s own comment about silent corruption risk) — but flag it explicitly in a code comment so it isn't mistaken for an oversight later.

Any field that ends up `None` after the fallback chain renders as `N/A` in the report — this function must never raise, and must never block report generation (wrap the `info.get()` calls defensively; a missing/failed forward-outlook fetch degrades to an all-`N/A` block, not a fatal error, consistent with `DataUnavailableError` being reserved for the core financials fetch only).

### 2.3 Wiring into `compute_metrics()` / `build_pdf_report()` / `build_markdown_report()`

- Call `compute_forward_outlook(info, trailing_pe, cagr)` inside `build_pdf_report()` right after `data = get_company_data(...)` — `info` isn't currently threaded out of `_fetch_once`/`get_company_data`'s return dict, so add `"info": info` to the dict returned by `_fetch_once` (financial_analyzer.py:223-238) and to `_sample_data()` (return `{}` there — sample data has no real consensus, forward outlook is all-`N/A` for `--allow-sample` runs, which is correct behavior).
- `trailing_pe = price / eps.iloc[-1]` if `eps.iloc[-1] > 0` else `None` (compute locally where needed; don't add it to `compute_metrics()`'s core return dict since it's a forward-outlook-only input).
- Store the result under a new key, e.g. `forward_outlook = compute_forward_outlook(...)`, passed alongside `m` into both renderers — keep it a sibling of `m`, not merged into it, since `compute_metrics()` is pure w.r.t. `data["financials"|"balance"|"cashflow"]` and shouldn't gain a dependency on `data["info"]` for its core sins/DCF logic.

### 2.4 Report section content and PEG color coding

New section (PDF: after section 3 DCF, before the technical-analysis warning callout; Markdown: new `## 4.` before the closing "что покупать" line) titled **"4. Форвардные мультипликаторы и консенсус-прогноз"**:

```
Forward P/E: {forward_pe:.2f}  [источник: {forward_pe_source}]   (или "N/A", если прибыль отрицательная/недоступна)
Ожидаемый рост (консенсус): {growth_rate*100:.1f}%  [источник: {growth_source}]
PEG Ratio: {peg_ratio:.2f}  [источник: {peg_source}]
```

PEG color coding (mirrors existing `val_color_key` pattern — `COLORS["success"/"warning"/"danger"]`):

| PEG | color | label |
|---|---|---|
| `< 1.0` | success | "Недооценена с учетом роста" |
| `1.0 – 2.0` | warning | "Оценена справедливо" |
| `> 2.0` | danger | "Переоценена относительно роста" |
| `None`/N/A | muted | "Недостаточно данных" |

This section is purely informational — it does **not** feed into the Section 1 verdict score. It's consensus/forward context sitting beside the express-checklist verdict, not a new sin.

---

## Section 3 — Qualitative Catalysts Block

### 3.1 Mechanism

Catalysts (product launches, regulatory shifts, reputational-crisis recovery, etc.) aren't fetchable data — they're an analyst's judgment call. Add an optional CLI input rather than trying to auto-generate or auto-fetch this:

```python
parser.add_argument(
    "--catalysts", type=str, default=None,
    help="Free-text note on catalysts/risks to embed in the report (e.g. product launch, regulatory event).",
)
parser.add_argument(
    "--catalysts-file", type=str, default=None,
    help="Path to a text file with the catalysts note (alternative to --catalysts).",
)
```

Mutually exclusive — if both are passed, raise `SystemExit("--catalysts and --catalysts-file are mutually exclusive")` before any fetch happens (fail fast on a user input error, don't waste a Yahoo Finance round-trip first).

Resolution order in `build_pdf_report(ticker, ..., catalysts=None, catalysts_file=None)`:

```python
if catalysts and catalysts_file:
    raise SystemExit("--catalysts and --catalysts-file are mutually exclusive")
catalysts_text = catalysts or (open(catalysts_file, encoding="utf-8").read().strip() if catalysts_file else None)
```

### 3.2 Rendering

New section **"5. Катализаторы и риски (качественная оценка)"** (after the Forward Outlook section, before the technical-analysis warning callout):

- If `catalysts_text` is provided: render it verbatim (through `escape_xml` in the PDF path, plain in Markdown) inside a neutral-colored `CalloutBox` (`COLORS["muted"]` bar).
- If not provided: render the placeholder — "Катализаторы не указаны — заполните вручную перед принятием решения. Справедливая стоимость по DCF может не реализовываться рынком годами без триггера переоценки." This placeholder text itself is the report's reminder of *why* the section exists, not filler — keep it even though no other section in this codebase carries a "why this matters" line, since this is the one section that has no auto-computed fallback at all.

No new dependency, no auto-generation, no invented figures — consistent with the project's existing `DataUnavailableError` philosophy of never presenting a plausible-looking placeholder as if it were real.

---

---

## Section 4 — Sector Suitability Guardrail (Financials & REITs)

### 4.1 Problem

Current Ratio, goodwill-adjusted long-term solvency, and standard FCF-based DCF are mathematically invalid for Financial Services (banks, insurance, capital markets — no conventional Current Assets/Liabilities layout) and REITs (valued on FFO/AFFO, not FCF). Running the analyzer on `JPM` or `O` today either silently corrupts the checklist (via `find_row`'s zero-filled default when a row genuinely doesn't exist for that sector) or produces a confidently wrong SKIP/BUY verdict. Default behavior must be **fail-fast**, not a warn-and-continue — a wrong verdict here is worse than a refusal.

### 4.2 Exception type

Follow the existing `DataUnavailableError` pattern (financial_analyzer.py:128-144) exactly — a typed exception the `__main__` block already knows how to catch and turn into a clean `SystemExit(1)`:

```python
class UnsupportedSectorError(Exception):
    """Raised when the ticker's sector makes the express checklist and standard
    FCF-based DCF mathematically invalid (Financial Services, REITs).

    Unlike DataUnavailableError, this isn't a transient condition — retrying
    won't help. Callers pass --force to proceed anyway, which does not raise
    this but instead threads a warning banner into the generated report.
    """

    def __init__(self, ticker, sector, industry):
        super().__init__(
            f"Тикер {ticker} относится к сектору {sector} ({industry}). "
            "Экспресс-методика и классический FCF-DCF не применимы к финансовым "
            "компаниям и REIT (см. --force для запуска с явным предупреждением)."
        )
        self.ticker = ticker
        self.sector = sector
        self.industry = industry
```

### 4.3 Detection

Runs in `build_pdf_report()`, right after `data = get_company_data(...)` succeeds and before `compute_metrics(data)` is called — uses the `data["info"]` dict already threaded through in Section 2.3.

```python
def _check_sector_suitability(ticker, info, force):
    sector = info.get("sector", "") or ""
    industry = info.get("industry", "") or ""
    is_financial = sector == "Financial Services"
    is_reit = sector == "Real Estate" and (
        "REIT" in industry.upper() or industry == "Real Estate - REITs"
    )
    if (is_financial or is_reit) and not force:
        raise UnsupportedSectorError(ticker, sector, industry)
    return (sector, industry) if (is_financial or is_reit) else (None, None)
```

Note the REIT rule is deliberately narrower than the whole "Real Estate" sector — plain real estate developers/operators (e.g. industry `"Real Estate - Development"`) go through unaffected since they report conventional current assets/liabilities and generate real FCF; only the FFO-valued REIT subset is excluded.

`_sample_data()` (financial_analyzer.py:244-288) has no `info` key today — Section 2.3 already specifies adding `"info": {}` there, so `_check_sector_suitability` on sample data always sees `sector=""` and passes through untouched (no behavior change for `--allow-sample` demos).

### 4.4 `--force` override and warning banner

New CLI flag, alongside `--allow-sample` in the existing `argparse` block (financial_analyzer.py:1216-1234):

```python
parser.add_argument(
    "--force", action="store_true",
    help="Generate the report even for sectors (Financials, REITs) where the express "
         "methodology and standard FCF-DCF are known to be invalid. Injects a warning banner.",
)
```

Threaded through `build_pdf_report(ticker, ..., force=False)`. When `_check_sector_suitability` returns a non-`None` sector (i.e. excluded sector + `--force` was passed), both renderers must inject a banner **before** section 1, not folded into the existing sins `CalloutBox`:

- **PDF** (`build_pdf_report`, right after the title/subtitle block, before section 1's `h1_style` heading): a full-width `CalloutBox` in `COLORS["danger"]` with bold text: `"⚠ ВНИМАНИЕ: компания относится к сектору {sector} ({industry}). Экспресс-оценка ликвидности и классический FCF-DCF в этом отчете могут быть некорректны для данного типа бизнеса."` — routed through `escape_xml` like every other user-facing string in this file.
- **Markdown** (`build_markdown_report`): same text as a `> ⚠ **ВНИМАНИЕ:**` blockquote immediately under the title line, before "## 1. Экспресс-вердикт".

`__main__` wiring, alongside the existing `except DataUnavailableError` (financial_analyzer.py:1242-1244):

```python
except UnsupportedSectorError as e:
    print(f"FAILED: {e}")
    raise SystemExit(1)
```

### 4.5 Test cases

1. `sector="Financial Services"`, no `--force` → `UnsupportedSectorError` raised, no report files written.
2. `sector="Financial Services"`, `--force` passed → report generates, banner text present in both PDF story and `.md` output.
3. `sector="Real Estate"`, `industry="Real Estate - REITs"`, no `--force` → raises.
4. `sector="Real Estate"`, `industry="Real Estate - Development"`, no `--force` → passes through unaffected, no banner, normal report.
5. Any other sector (e.g. `"Technology"`) → unaffected regardless of `--force` value (banner never injected when the sector isn't excluded, even if `--force` was passed for a routine ticker).
6. `--allow-sample` run (no real `info`) → unaffected, passes through, no banner — sample-data demos must keep working exactly as today.

---

*(Spec complete — 4 sections covering all actionable items from the feedback report. Sections already shipped in the current codebase — goodwill deduction, long-term solvency check, CR<2.0 trend gating, operating-income trend sin — are not repeated here.)*
