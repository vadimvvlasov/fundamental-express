# AGENTS.md — fundamental-express

## Stack / commands
- Python 3.13 only (`.python-version`). Deps pinned in `pyproject.toml` / `uv.lock`.
- `uv sync` to install. Without uv: `pip install yfinance pandas numpy matplotlib reportlab`.
- `uv run pytest` — tests. `pyproject.toml: [tool.pytest.ini_options] pythonpath = [".", "src"]`, do not change.
- Single ticker: `uv run python financial_analyzer.py MCD [--retries 5 --retry-delay 5 --allow-sample --catalysts "..." --catalysts-file f.txt --force --required-return 0.12]`
- Portfolio: `uv run python portfolio_analyzer.py TICKER:WEIGHT ... [--name X --required-return 0.10]` (e.g. `TSM:14 SAP:13`, weights need not sum to 100, `BRK.B:10` allowed).
- PDF cyrillic needs `DejaVu Sans` at `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` (`apt install fonts-dejavu-core`). Missing font → Helvetica fallback = unreadable Russian glyphs + one console warning.
- Never commit `output/`, `scratch/*.png`, `*_fundamental_report*.pdf` — all generated, all in `.gitignore`. Regenerate via CLIs.

## Architecture — where to edit
- `src/fundamental_express/data/` — network/FS only: `yahoo.py` (fetch + retries + FX bridge), `parsing.py` (`find_row`, year alignment), `errors.py` (`DataUnavailableError`, `UnsupportedSectorError`), `sample.py` (SAMPLE fallback).
- `src/fundamental_express/domain/` — pure logic, no I/O: `ordinary.py` / `bank.py` / `reit.py` (checklist conditions), `sins.py` (registry + `score()`, thresholds BUY ≤ 1.0 / WATCH ≤ 2.5), `valuation.py` (CAPM/WACC/DCF, DDM, ROE-P-B, NAV, forward multiples), `metrics.py` (`OrdinaryMetrics` / `BankMetrics` / `ReitMetrics`), `routing.py` (`check_sector_suitability`, `_is_reit`), `graham.py`.
- `src/fundamental_express/reporting/` — `theme.py` / `flowables.py` / `tables.py` / `charts.py` (sector-agnostic primitives) + `sections_ordinary.py` / `sections_bank.py` / `sections_reit.py` (per-sector section lists) + universal `pdf.py` / `markdown.py` renderers. Never add a per-sector report builder; add sections.
- `src/fundamental_express/cli/` — `args.py` (`required_return_type`), `catalysts.py`, `paths.py` (`SCRIPT_DIR` / `SCRATCH_DIR` / `OUTPUT_DIR`, auto-`makedirs`), `single_ticker.py`, `portfolio.py`.
- `analyzers.py: AnalyzerFactory` — sole router: `sector == "Financial Services"` → `BankAnalyzer`, `_is_reit(info)` → `ReitAnalyzer`, else `OrdinaryAnalyzer`. `financial_analyzer.py` / `portfolio_analyzer.py` are thin shims — keep `python financial_analyzer.py TICKER` and `python portfolio_analyzer.py ...` working unchanged.
- Import bootstrap: `src/` is not installed. Root files do `sys.path.insert(0, <root>/src)`; `analyzers.py` / `cli/*` rely on the `import financial_analyzer` side effect for `sys.path`. Preserve re-exports in `financial_analyzer.py` (`MAX_MINOR_SCORE`, `BANK_MAX_MINOR_SCORE`, `REIT_MAX_MINOR_SCORE`, `compute_metrics`, `compute_bank_metrics`, `compute_reit_metrics`, `find_row`, errors, `CATALYSTS_PLACEHOLDER`, `required_return_type`) — tests import from there.

## Hard rules (past bugs came from violating these)
- No mock fallback: default is `DataUnavailableError`, exit 1. `--allow-sample` is demo-only for single ticker; portfolio has no sample mode. Never substitute plausible numbers for a real ticker.
- `find_row()`: exact match over all keywords first, then partial. Never reorder — old order matched `Reconciled Cost Of Revenue` for `revenue` and blew margins over 100%.
- FX bridge: if `info["financialCurrency"] != info["currency"]` (e.g. TSM TWD vs USD), convert ALL money rows via `{FCY}{CCY}=X` (e.g. `TWDUSD=X`) before valuation; never convert EPS / share counts. FX failure = retry, not silent mixed-currency math.
- Missing rows → `NaN` (skip that check), never `0.0`, unless spec says otherwise. Leniency is never granted on missing data (e.g. CR smart-bypass requires a real `Current Debt` row).
- Debt duality, do not merge: WACC weight uses interest-bearing debt (`Long Term Debt` → `Total Debt incl. leases` → 0); equity bridge uses separate Net Debt (Yahoo `Net Debt` preferred with source label `reported`, else debt − cash). Leases excluded from headline net debt as a documented assumption (FCF is post-rent); always show `interest_bearing_debt` / `lease_liabilities` / `total_debt_incl_leases` separately.
- Fixed methodology assumptions, do not "fix": `Rf=4%, ERP=5%, Kd=4.5%, T=21%, terminal g=2.5%, CAGR∈[2,15]% (default 5%), WACC∈[5,15]%, beta fallback 1.1`. Verdict comes from the sins checklist, never from DCF price.
- `--force` / `check_sector_suitability()` is currently a no-op gate (all sectors have real engines) — keep it for future sectors and the warning-banner path exercised by tests.
- `--required-return 0.05–0.25` replaces CAPM Ke; reject `15`-style percents with a hint, no clamping. `--catalysts` ⊕ `--catalysts-file`, else print placeholder — never invent catalysts. `--analyst-notes` ⊕ `--analyst-notes-file` (both in `cli/catalysts.py`, threaded via `analyst_notes_text` through `analyzers.py` into `build_*_sections(..., analyst_notes)`) appends a trailing verbatim "Заметки аналитика" section (№6 ordinary / №5 bank+reit) — absent when not given. Convention: write it to `output/<TICKER>_analyst_notes_<date>.md` so the file sits next to the report and is also embedded in it. Analyst-supplied text must avoid `&`/`<`/`>` (breaks the ReportLab path — same limitation as catalysts).

## Tests / docs
- Tests build 2-year synthetic DataFrames (see `tests/test_verdict_scoring.py: make_data`) and call `compute_*_metrics()` directly — no `yfinance`, no FS. Follow that pattern for new sins/valuation. Golden markdown tests live in `tests/golden/`.
- `docs/spec/*.md` is the spec source of truth; `README.md` is user-facing methodology + changelog. Update both when changing weights/formulas. Keep Russian verdict strings byte-identical (`🟢 КУПИТЬ / СИЛЬНЫЙ КАНДИДАТ`, `🟡 НАБЛЮДАТЬ / ОГРАНИЧЕННАЯ ДОЛЯ`, `🔴 ПРОПУСТИТЬ / ВЫСОКИЙ РИСК`).
