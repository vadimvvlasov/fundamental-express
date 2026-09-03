# Follow-up issues

Filed (not yet groomed) — each one is something an acceptance criterion in a
V0x issue deliberately pushed out of scope. When one of these gets picked up,
run it through `_docs/task-template.md` properly before implementation.

---

<a id="fu-01-nonrecurring-detection"></a>
### FU-01 — Auto-detect non-recurring items beyond yfinance's explicit rows
**Parent:** [V03](./V03-normalize-nonrecurring-items.md)
**Problem:** V03 only strips items yfinance exposes as their own statement
row (impairment, unusual items). It has no way to catch a one-off buried
inside an ordinary-looking line (e.g. a litigation settlement folded into
"Other Operating Expenses"). Real normalization would need either a second
data source or text-parsing of the 10-K/10-Q footnotes — out of V03's
budget.
**Status:** not groomed.

---

<a id="fu-08-inconsistent-debt-basis"></a>
### FU-08 — `debt`/net debt silently switches lease basis depending on data availability, not sector
**Parent:** [V04](./V04-lease-adjusted-net-debt.md) (found while grooming, not part of the
original backlog entry)
**Problem:** `financial_analyzer.py:178`:
`debt = interest_bearing_debt if not interest_bearing_debt.isna().all() else
total_debt_incl_leases`. When yfinance doesn't expose a separate "Long Term
Debt" row for a ticker, `debt` (and therefore today's single "net debt")
silently becomes lease-*inclusive* for that ticker — while every other
ticker with complete data stays lease-*excluded*. The report's headline
number is computed on a different basis from one ticker to the next, purely
because of yfinance data completeness, with no visible flag either way.
V04 works around this locally (checks which case applies before adding
`lease_liabilities`, to avoid double-counting), but does not fix the
underlying inconsistency in today's single headline number, because doing
so changes that headline for an unrelated set of tickers — a separate,
deliberate decision, not a side effect of adding a secondary figure.
**Status:** not groomed.

---

<a id="fu-02-lease-heavy-sector-taxonomy"></a>
### FU-02 — Maintained lease-heavy sector taxonomy
**Parent:** [V04](./V04-lease-adjusted-net-debt.md)
**Problem:** V04 ships a short hardcoded keyword list (retail/airlines/
restaurants) to decide which sector gets lease-inclusive net debt as the
headline number. That list will go stale and won't cover every lease-heavy
industry (hospitality, healthcare facilities, telecom towers). Needs an
owned, periodically-reviewed taxonomy — separate from a single-PR fix.
**Status:** not groomed.

---

<a id="fu-03-rating-based-kd"></a>
### FU-03 — Credit-rating-based cost of debt
**Parent:** [V05](./V05-implied-cost-of-debt.md)
**Problem:** V05 only derives Kd from the company's own Interest Expense /
Total Debt (an implied rate). A materially better Kd would use the
company's actual bond spread off its credit rating (S&P/Moody's), which
this codebase has no data source for today (yfinance doesn't expose credit
ratings). Needs a new data provider integration.
**Status:** not groomed.

---

<a id="fu-04-live-risk-free-rate"></a>
### FU-04 — Live risk-free rate instead of the static 4% constant
**Parent:** [V06](./V06-reit-cap-rate-rate-regime.md)
**Problem:** V06 reuses the existing hardcoded `rf_rate = 0.04` constant
(shared with the DCF/DDM models) so the REIT cap rate at least moves when
that constant is edited by hand. It does not fetch a live 10-Year Treasury
yield. Doing that is a new external dependency (data source, caching,
staleness/outage handling) — a separate task, and it would also change Ke
for every Ordinary/Bank valuation, not just REIT, so it needs its own
design discussion, not a REIT-scoped fix.
**Status:** not groomed.

---

<a id="fu-05-peer-beta-relever"></a>
### FU-05 — Full Hamada relever with peer-group beta
**Parent:** [V08](./V08-beta-sanity-check.md)
**Problem:** V08 only clamps obviously-broken beta values (negative, or
implausibly high) to a fallback with a report disclosure. A methodologically
correct fix (unlever peers' beta by their own D/E, average, relever at the
subject company's D/E) needs a peer-group definition (by sector? by size?)
that doesn't exist anywhere in this codebase yet — a bigger design question
than a sanity clamp.
**Status:** not groomed.

---

<a id="fu-06-consensus-terminal-growth"></a>
### FU-06 — Analyst-consensus-driven terminal growth per company
**Parent:** [V09](./V09-sector-terminal-growth.md)
**Problem:** V09 only replaces the single flat 2.5% with a small
sector-bucketed table (same pattern as `REIT_CAP_RATE_MATRIX`). A
per-company terminal growth informed by analyst long-term consensus
estimates would be more precise but needs a consensus-data source this
codebase doesn't currently fetch (Forward P/E and PEG consensus fields
exist for the *forward outlook* section only, not wired into the DCF
terminal-value calculation).
**Status:** not groomed.

---

<a id="fu-07-full-graham-method"></a>
### FU-07 — Full historical Graham method
**Parent:** [V10](./V10-graham-number-reproducible.md)
**Problem:** V10 only makes the single-year `√(22.5 × EPS_ttm × tangible_BVPS)`
formula reproducible in code. Graham's original method used a multi-year
average EPS (to smooth cyclicality) and a separate current-assets-vs-total-
liabilities solvency test as a companion filter, neither of which V10
implements. Whether this project wants the full classical screen (vs. the
simplified single-year ceiling it already documents as "справочно, вне
основной методики") is a product decision, not implied by V10.
**Status:** not groomed.
