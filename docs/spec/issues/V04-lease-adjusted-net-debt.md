# V04 — Surface a lease-inclusive fair value as the headline for lease-heavy sectors

## Problem
`net_debt` in the Ordinary DCF (`financial_analyzer.py:282-291`) excludes
operating lease liabilities by design — a documented methodology choice,
disclosed in the rendered report:

> "Допущение по лизингу: в базовом DCF обязательства по аренде исключены
> из net debt..." (`sections_ordinary.py:31-34`)

The two numbers needed to compute a lease-inclusive alternative are already
fetched and already shown in the report as footnote figures —
`m.lease_liabilities` and `m.total_debt_incl_leases`
(`sections_ordinary.py:50-60`) — but nothing downstream ever uses them to
compute a second Enterprise/Equity/fair value. For a lease-heavy business
(retail, airlines, restaurants), the *only* number the report treats as
"the" fair value is the lease-excluded one, which can materially
understate net debt and overstate equity value for exactly the sector
where operating leases are economically closest to debt.

## Acceptance Criteria
- [ ] A second `net_debt_incl_leases = net_debt + lease_liabilities` is
      computed whenever `lease_liabilities` is available (fallback to
      `total_debt_incl_leases − cash` when `lease_liabilities` is `NaN`
      but `total_debt_incl_leases` is present — see Edge Cases for why
      these must not both be applied at once).
- [ ] A second fair value (`fair_value_share_incl_leases`) is computed
      through the same DCF machinery, using `net_debt_incl_leases` instead
      of `net_debt`, and is always rendered in the report next to the
      primary fair value — labeled plainly (e.g. "Fair value (с учётом
      аренды как долга)") — regardless of sector, so a reviewer never has
      to trust a sector classifier to see the alternate number.
- [ ] A small sector/industry keyword classifier (mirroring the existing
      `_is_reit(info)` pattern in `domain/routing.py`) decides which of
      the two numbers is the *headline* "Справедливая стоимость акции"
      used for the buy/hold/skip verdict — lease-heavy keywords (retail,
      airline, restaurant to start) get the lease-inclusive number as
      headline; everything else keeps today's lease-excluded number as
      headline, unchanged.
- [ ] Given a fixture ticker tagged with a lease-heavy industry string and
      nonzero `lease_liabilities`, the rendered report's headline
      "Справедливая стоимость акции" line matches the lease-inclusive
      calculation, and the lease-excluded number still appears alongside
      it, clearly labeled as the secondary figure.
- [ ] Given a fixture ticker *not* tagged lease-heavy, the headline number
      is byte-identical to today's output, and the lease-inclusive number
      appears as the secondary figure (not the reverse of the case above —
      this is symmetric, both numbers always shown, only which one is
      "headline" changes by sector).
- [ ] `pytest -q` passes, with new tests for: lease-heavy ticker headline
      selection, non-lease-heavy ticker no-op, and the
      `lease_liabilities`-missing fallback to `total_debt_incl_leases`.

## Edge Cases Considered
- **`debt` (used for `net_debt` today) is sometimes *already*
  lease-inclusive, inconsistently, before this task even starts.**
  `financial_analyzer.py:178`:
  `debt = interest_bearing_debt if not interest_bearing_debt.isna().all()
  else total_debt_incl_leases` — for a ticker where yfinance doesn't
  expose a separate "Long Term Debt" row, `debt` silently falls back to
  the lease-inclusive `total_debt_incl_leases`, meaning today's "primary"
  net debt is lease-*excluded* for most tickers but lease-*inclusive* for
  some, depending purely on yfinance's data completeness for that ticker —
  not on sector. This task's `net_debt_incl_leases` calculation must check
  which case `debt` is already in for the given ticker (via
  `interest_bearing_debt.isna().all()`) and add `lease_liabilities` only
  when `debt` is *not* already lease-inclusive, to avoid double-counting
  leases. The pre-existing inconsistency itself (today's single headline
  number silently switching basis by data availability, not sector) is a
  real, separate bug this task's investigation surfaced — tracked on its
  own, not silently fixed as a side effect here, since fixing it changes
  today's headline number for an unrelated set of tickers →
  see [FU-08](./follow-ups.md#fu-08-inconsistent-debt-basis).
- **Neither `lease_liabilities` nor `total_debt_incl_leases` available for
  a lease-heavy-tagged ticker.** Render the secondary figure as "N/A" with
  a one-line note, and keep the headline on the lease-excluded number for
  that ticker specifically (never silently reclassify to lease-inclusive
  without the data to support it) — the sector tag alone is not sufficient
  to justify the switch if the underlying figure can't be computed.
- **A company genuinely has zero lease liabilities despite a lease-heavy
  sector tag** (e.g. owns all its real estate outright). Both numbers
  converge to the same value — no special-case needed, the calculation
  naturally produces `net_debt_incl_leases == net_debt` when
  `lease_liabilities == 0`.
- **Bank/REIT tickers.** This task is scoped to the Ordinary DCF path only
  (`ordinary_dcf_valuation`) — Bank already has no EV/net-debt concept
  (`FOOTERS["bank"]` in `reporting/markdown.py` says so explicitly), and
  REIT's NAV already nets `total_liab` in full (`valuation.py:357`,
  `nav = property_value + ... - latest_total_liab`), which already
  includes lease liabilities as part of total liabilities — no equivalent
  gap exists there.

## Out of Scope
- Building and maintaining a comprehensive, industry-taxonomy-backed
  lease-heavy sector list beyond the small starter keyword set (retail,
  airlines, restaurants) → see
  [FU-02](./follow-ups.md#fu-02-lease-heavy-sector-taxonomy).
- Fixing the pre-existing inconsistency where `debt` (and therefore
  today's single lease-excluded headline) is silently lease-inclusive for
  some tickers based on data availability, independent of this task's new
  secondary figure → see [FU-08](./follow-ups.md#fu-08-inconsistent-debt-basis).
