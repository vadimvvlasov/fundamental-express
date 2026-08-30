# Task List: Modular Refactor of `fundamental-express`

Status: DRAFT — planning only. Do not start execution without explicit approval.
Companion to `docs/spec/refactor-architecture-spec.md` (read that first for the target
layout, dataclasses, sin registry, and section model referenced by id below).

## Conventions

- Every task is independently mergeable: after it lands, `pytest` passes and both
  `python financial_analyzer.py <ticker> --allow-sample` and
  `python portfolio_analyzer.py <ticker>:<shares> --allow-sample` still run to completion.
- `financial_analyzer.py` keeps re-exporting every symbol it currently exports (as a thin
  `from fundamental_express.x import y` shim) until the deletion task (T18) — nothing outside
  the task being executed is allowed to break mid-sequence.
- "Rollback" means `git revert <task commit>` cleanly, since each task is its own commit.
- Prerequisite ids are listed flat; tasks with no dependency on each other may be done in any
  order or in parallel by different people.

---

### T01 — Golden-output characterization harness
**Goal:** commit a network-free, byte-diff safety net for markdown output before any
production code moves.
**Creates:** `tests/golden/fixtures/ordinary_data.py`, `tests/golden/fixtures/bank_data.py`,
`tests/golden/fixtures/reit_data.py` (hand-built dicts shaped exactly like `get_company_data`'s
return value — `info`, `financials`, `balance_sheet`, `cashflow`, `price`, etc. — for one
ordinary ticker, one bank, one REIT), `tests/golden/snapshots/ordinary.md`,
`tests/golden/snapshots/bank.md`, `tests/golden/snapshots/reit.md` (committed output of
`build_markdown_report`/`build_bank_markdown_report`/`build_reit_markdown_report` run against
those fixtures), `tests/test_golden_markdown.py` (feeds each fixture through
`compute_*_metrics` + `build_*_markdown_report` and diffs against the snapshot).
**Prerequisites:** none.
**Acceptance:** `pytest tests/test_golden_markdown.py -v` passes, and it fails (byte diff
shown) if any snapshot file is hand-edited by one character.
**Rollback:** delete `tests/golden/`.

---

### T02 — Extract theme (colors, fonts, page geometry, `escape_xml`, `_fmt_or_na`)
**Goal:** move the zero-dependency visual constants out first.
**Creates:** `src/fundamental_express/reporting/theme.py`.
**Moves:** `COLORS`, font registration block, `FONT_NAME`, `FONT_BOLD`, `PAGE_SIZE`,
`MARGIN`, `PAGE_W`, `PAGE_H`, `USABLE_W`, `escape_xml`, `_fmt_or_na` out of
`financial_analyzer.py`, replaced there with
`from fundamental_express.reporting.theme import *`-equivalent named re-exports.
**Prerequisites:** none.
**Acceptance:** `pytest && python financial_analyzer.py AAPL --allow-sample`.
**Rollback:** revert commit; shim keeps old imports working either way.

---

### T03 — Extract flowables (`SectionDivider`, `CalloutBox`, `SectorWarningBanner`)
**Goal:** move the three custom ReportLab `Flowable` subclasses.
**Creates:** `src/fundamental_express/reporting/flowables.py`.
**Prerequisites:** T02 (imports `theme.COLORS`).
**Acceptance:** `pytest && python financial_analyzer.py AAPL --allow-sample`.
**Rollback:** revert commit.

---

### T04 — Extract tables (`create_reportlab_table`)
**Goal:** move the shared table-building helper.
**Creates:** `src/fundamental_express/reporting/tables.py`.
**Prerequisites:** T02.
**Acceptance:** `pytest && python financial_analyzer.py AAPL --allow-sample`.
**Rollback:** revert commit.

---

### T05 — Extract charts (`generate_fcf_chart`, `generate_nii_chart`, `generate_ffo_chart`)
**Goal:** move the three Matplotlib chart functions.
**Creates:** `src/fundamental_express/reporting/charts.py`.
**Prerequisites:** none.
**Acceptance:** `pytest && python financial_analyzer.py AAPL --allow-sample`.
**Rollback:** revert commit.

---

### T06 — Extract statement parsing (`find_row`, `_align_statement_years`)
**Goal:** move the data-layer parsing helpers with no fetch/network dependency.
**Creates:** `src/fundamental_express/data/parsing.py`.
**Prerequisites:** none.
**Acceptance:** `pytest && python financial_analyzer.py AAPL --allow-sample`.
**Rollback:** revert commit.

---

### T07 — Extract errors (`DataUnavailableError`, `UnsupportedSectorError`)
**Goal:** move the two exception classes; `portfolio_analyzer.py` and `analyzers.py` both
import these directly, so this is a leaf with two known call sites to update.
**Creates:** `src/fundamental_express/data/errors.py`.
**Prerequisites:** none.
**Acceptance:** `pytest && python financial_analyzer.py AAPL --allow-sample && python portfolio_analyzer.py AAPL:10 --allow-sample`.
**Rollback:** revert commit.

---

### T08 — Extract routing (`check_sector_suitability`, `_is_reit`)
**Goal:** move the sector-routing helpers (dormant restriction + REIT-industry sniff) out of
`financial_analyzer.py`/`analyzers.py`.
**Creates:** `src/fundamental_express/domain/routing.py`.
**Prerequisites:** T07 (raises `UnsupportedSectorError`).
**Acceptance:** `pytest && python financial_analyzer.py AAPL --allow-sample`.
**Rollback:** revert commit.

---

### T09 — Extract data layer (`_fetch_once`, `_fx_rate`, `_sample_data`, `get_company_data`)
**Goal:** isolate every yfinance/network call behind `data/yahoo.py` + `data/sample.py`.
**Creates:** `src/fundamental_express/data/yahoo.py`, `src/fundamental_express/data/sample.py`.
**Prerequisites:** T06 (uses `find_row`), T07 (raises `DataUnavailableError`).
**Acceptance:** `pytest && python financial_analyzer.py AAPL --allow-sample && python financial_analyzer.py AAPL --retries 1`.
**Rollback:** revert commit.

---

### T10 — Introduce dataclasses (`ScoringResult`, `ValuationResult`, `OrdinaryMetrics`,
`BankMetrics`, `ReitMetrics`)
**Goal:** define the target shapes (spec Section 3) without yet wiring them in — pure
addition, `compute_*_metrics` still return dicts.
**Creates:** `src/fundamental_express/domain/metrics.py`.
**Prerequisites:** none.
**Acceptance:** `pytest` (new file only, imported by nothing yet, so this task cannot break
anything at runtime — the check is that `python -c "import fundamental_express.domain.metrics"`
succeeds).
**Rollback:** delete the file.

---

### T11 — Declarative sin registry (`domain/sins.py`)
**Goal:** build `SinSpec`, the three per-asset-class registries (weights copied verbatim from
`MINOR_SIN_WEIGHTS`/`BANK_MINOR_SIN_WEIGHTS`/`REIT_MINOR_SIN_WEIGHTS`), `fire()`, and the one
`score()` function (spec Section 4), as a pure addition alongside the existing three
hand-written scoring blocks — not yet called by `compute_*_metrics`.
**Creates:** `src/fundamental_express/domain/sins.py`, `tests/test_sins_registry.py`
(asserts `score()` against hand-picked sin lists reproduces every verdict/minor_score
combination the existing `tests/test_verdict_scoring.py` already covers).
**Prerequisites:** T10 (`Sin`, `ScoringResult`).
**Acceptance:** `pytest tests/test_sins_registry.py -v`.
**Rollback:** delete the two new files.

---

### T12 — Extract valuation models (`domain/valuation.py`)
**Goal:** move CAPM/WACC/DCF, DDM, NAV, ROE-P-B, the REIT cap-rate matrix, and
`compute_forward_outlook`/`_peg_assessment` out of the three `compute_*_metrics` functions,
as pure functions taking explicit arguments (statement series, beta, required_return) and
returning `ValuationResult` plus any asset-class-specific extra fields.
**Creates:** `src/fundamental_express/domain/valuation.py`.
**Prerequisites:** T10.
**Acceptance:** `pytest` (valuation functions are called with the same inputs the existing
`compute_*_metrics` tests already exercise, asserted equal to today's dict values).
**Rollback:** revert commit.

---

### T13 — Rewire `compute_metrics` onto `OrdinaryMetrics` (ordinary domain engine)
**Goal:** `financial_analyzer.compute_metrics` becomes a thin wrapper: run ordinary condition
checks (kept in place), call `domain.sins.score()` and `domain.valuation`, assemble
`OrdinaryMetrics`, and — until T16 — convert it back to today's dict shape at the return
boundary so every caller keeps working unchanged.
**Creates:** `src/fundamental_express/domain/ordinary.py` (condition checks moved from
`compute_metrics`).
**Prerequisites:** T11, T12.
**Acceptance:** `pytest tests/test_verdict_scoring.py tests/test_ordinary_v3.py -v && pytest tests/test_golden_markdown.py -v`.
**Rollback:** revert commit; `financial_analyzer.compute_metrics` still has its pre-T13 body
available in git history.

---

### T14 — Rewire `compute_bank_metrics` onto `BankMetrics` (bank domain engine)
**Goal:** same as T13, for the bank pipeline.
**Creates:** `src/fundamental_express/domain/bank.py`.
**Prerequisites:** T11, T12.
**Acceptance:** `pytest tests/test_bank_analyzer.py -v && pytest tests/test_golden_markdown.py -v`.
**Rollback:** revert commit.

---

### T15 — Rewire `compute_reit_metrics` onto `ReitMetrics` (REIT domain engine)
**Goal:** same as T13, for the REIT pipeline.
**Creates:** `src/fundamental_express/domain/reit.py`.
**Prerequisites:** T11, T12.
**Acceptance:** `pytest tests/test_reit_analyzer.py -v && pytest tests/test_golden_markdown.py -v`.
**Rollback:** revert commit.

---

### T16 — Switch dict callers to dataclass attribute access
**Goal:** now that all three engines produce dataclasses internally, drop the
dict-conversion boundary from T13/T14/T15 and update every caller
(`build_*_markdown_report`, `build_*_pdf_report`, `analyzers.py`, `portfolio_analyzer.py`,
and the `m["key"]` lookups across all 87 tests) to `m.field`/`m.scoring.field`/
`m.valuation.field` attribute access. No assertion changes — same values, same coverage.
**Creates:** nothing new; touches call sites only.
**Prerequisites:** T13, T14, T15.
**Acceptance:** `pytest -v && python financial_analyzer.py AAPL --allow-sample && python portfolio_analyzer.py AAPL:10 --allow-sample`.
**Rollback:** revert commit (largest diff in the sequence — split further if it exceeds
~400 lines once the actual call-site count is known).

---

### T17 — Section model + ordinary sections (`reporting/sections.py`, `sections_ordinary.py`)
**Goal:** define the `Section` protocol (spec Section 5) and build the ordered
`list[Section]` for the ordinary report (checklist table, DCF/sensitivity block, debt
disclosure, forward outlook) from `OrdinaryMetrics`, without yet touching
`build_markdown_report`/`build_pdf_report`.
**Creates:** `src/fundamental_express/reporting/sections.py`,
`src/fundamental_express/reporting/sections_ordinary.py`.
**Prerequisites:** T02–T05 (theme/flowables/tables/charts), T16.
**Acceptance:** `pytest` (new modules exercised by a new
`tests/test_sections_ordinary.py` that renders each section standalone and spot-checks
content against `OrdinaryMetrics` fixtures — not yet against the golden snapshot).
**Rollback:** delete the two new files.

---

### T18 — Bank and REIT sections (`sections_bank.py`, `sections_reit.py`)
**Goal:** same as T17 for bank (NII/provisions checklist, LTD/DDM disclosure) and REIT
(AFFO/occupancy checklist, NAV bridge, operating rows).
**Creates:** `src/fundamental_express/reporting/sections_bank.py`,
`src/fundamental_express/reporting/sections_reit.py`.
**Prerequisites:** T17 (shares the `Section` protocol).
**Acceptance:** `pytest`.
**Rollback:** delete the two new files.

---

### T19 — Unified markdown renderer
**Goal:** replace `build_markdown_report`/`build_bank_markdown_report`/
`build_reit_markdown_report` with one `reporting/markdown.py::render(ticker, data, metrics,
sections)` driven by T17/T18's section lists; delete the three old functions once the golden
snapshot (T01) matches byte-for-byte for all three asset classes.
**Creates:** `src/fundamental_express/reporting/markdown.py`.
**Deletes:** `build_markdown_report`, `build_bank_markdown_report`,
`build_reit_markdown_report` from `financial_analyzer.py`.
**Prerequisites:** T17, T18, T01.
**Acceptance:** `pytest tests/test_golden_markdown.py -v` (exact byte match against all three
committed snapshots).
**Rollback:** revert commit; the three deleted functions are recoverable from git history.

---

### T20 — Unified PDF renderer
**Goal:** same as T19 for `build_pdf_report`/`build_bank_pdf_report`/`build_reit_pdf_report`,
producing `reporting/pdf.py::render(ticker, data, metrics, sections)`. PDFs aren't
byte-reproducible (T01 is markdown-only), so acceptance here is generate-and-open, not diff.
**Creates:** `src/fundamental_express/reporting/pdf.py`.
**Deletes:** `build_pdf_report`, `build_bank_pdf_report`, `build_reit_pdf_report` (rendering
portion only — fetch/compute orchestration moves to `analyzers.py` in T21) from
`financial_analyzer.py`.
**Prerequisites:** T17, T18.
**Acceptance:** `pytest && python financial_analyzer.py AAPL --allow-sample && ls output/*.pdf`
(manual visual check: open the generated PDF, compare section order against the pre-refactor
PDF for the same ticker).
**Rollback:** revert commit.

---

### T21 — Fill `BaseAnalyzer`: real fetch → compute → render orchestration
**Goal:** close Problem 3 (layer collapse). `OrdinaryAnalyzer.generate_pdf_report()` /
`BankAnalyzer.generate_pdf_report()` / `ReitAnalyzer.generate_pdf_report()` stop re-fetching
and re-computing internally — they call `self.data`/`self.metrics` (already populated by
`fetch_data()`/`calculate_metrics()` per `BaseAnalyzer.analyze()`) and pass them straight to
`reporting/pdf.py::render()`/`reporting/markdown.py::render()` with the matching
`sections_*` list. `retries`/`retry_delay`/`allow_sample` move to being `fetch_data()`-only
concerns; `render()` never sees them.
**Creates:** nothing new; rewrites `analyzers.py`.
**Prerequisites:** T19, T20, T09.
**Acceptance:** `pytest -v && python financial_analyzer.py AAPL --allow-sample && python financial_analyzer.py JPM --allow-sample && python financial_analyzer.py PLD --allow-sample && python portfolio_analyzer.py AAPL:10,JPM:5 --allow-sample`.
**Rollback:** revert commit.

---

### T22 — CLI extraction (`cli/args.py`, `cli/catalysts.py`, `cli/paths.py`,
`cli/single_ticker.py`, `cli/portfolio.py`)
**Goal:** move `required_return_type`, `resolve_catalysts_text`/`CATALYSTS_PLACEHOLDER`,
`SCRIPT_DIR`/`SCRATCH_DIR`/`OUTPUT_DIR`, and both `argparse` entry points into `cli/`.
`financial_analyzer.py` and `portfolio_analyzer.py` become two-line shims that call into
`cli.single_ticker:main`/`cli.portfolio:main` so the documented `python financial_analyzer.py
<ticker>` invocation keeps working unchanged.
**Creates:** the five `cli/*.py` files listed above.
**Prerequisites:** T21.
**Acceptance:** `pytest -v && python financial_analyzer.py AAPL --allow-sample && python portfolio_analyzer.py AAPL:10 --allow-sample` (identical stdout/exit code to a pre-task run captured for comparison).
**Rollback:** revert commit.

---

### T23 — Delete emptied modules, drop the shim
**Goal:** once every symbol has moved and every caller uses the new import paths,
`financial_analyzer.py` and `portfolio_analyzer.py` shrink to nothing (or are deleted outright
if the CLI contract can be satisfied by `python -m fundamental_express.cli.single_ticker`
instead — confirm which the user prefers before this task, since it's the one place a CLI
invocation could visibly change; if the answer is "keep the exact `python financial_analyzer.py`
invocation," this task keeps the two-line shim from T22 permanently instead of deleting it).
**Prerequisites:** T22.
**Acceptance:** `pytest -v && ls src/fundamental_express/ && python financial_analyzer.py AAPL --allow-sample`.
**Rollback:** revert commit.

---

### T24 — README update
**Goal:** rewrite the architecture section to describe the real package layout and correct
the stale "BankAnalyzer/ReitAnalyzer are stubs" claim (`README.md:14`) to reflect that both
are full implementations with their own checklist/valuation engines, plus a short "package
layout" section pointing at `src/fundamental_express/{data,domain,reporting}`.
**Creates:** nothing; edits `README.md` only.
**Prerequisites:** T23.
**Acceptance:** manual read-through; no command (a README has no test).
**Rollback:** revert commit.

---

## Ordering summary

```
T01 (harness)
T02 → T03, T04                    (theme leaf, then its two dependents)
T05, T06, T07                     (independent leaves: charts, parsing, errors)
T08 (needs T07)
T09 (needs T06, T07)              (data layer complete)
T10 (dataclasses, standalone)
T11 (needs T10)                   (sin registry)
T12 (needs T10)                   (valuation models)
T13, T14, T15 (need T11, T12)     (three domain engines rewired — parallelizable)
T16 (needs T13, T14, T15)         (dict → dataclass call sites)
T17 (needs T02-T05, T16)
T18 (needs T17)
T19 (needs T17, T18, T01)         (markdown renderer, golden-diffed)
T20 (needs T17, T18)              (PDF renderer)
T21 (needs T19, T20, T09)         (analyzer orchestration, layer collapse fixed)
T22 (needs T21)                   (CLI extraction)
T23 (needs T22)                   (delete shims)
T24 (needs T23)                   (README)
```

24 tasks. T02/T05/T06/T07/T10 can start immediately and in parallel. T13/T14/T15 are the
first point every prior leaf extraction must have landed.
