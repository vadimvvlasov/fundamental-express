"""Exceptions raised by the data-fetching layer. Moved verbatim out of
financial_analyzer.py (docs/spec/refactor-tasks.md T07).
"""


class DataUnavailableError(Exception):
    """Raised when real market data could not be fetched after retries.

    We never silently substitute mock numbers for a real ticker analysis -
    that produces a plausible-looking PDF full of numbers that belong to
    nobody. Callers either handle this (retry later, tell the user) or let
    it propagate.
    """

    def __init__(self, ticker, attempts):
        super().__init__(
            f"Could not fetch real market data for '{ticker}' from Yahoo Finance "
            f"after {attempts} attempt(s). Yahoo Finance is often just flaky - "
            f"rerun in a minute or two."
        )
        self.ticker = ticker
        self.attempts = attempts


class UnsupportedSectorError(Exception):
    """Raised when the ticker's sector makes the express checklist and standard
    FCF-based DCF mathematically invalid - see
    docs/spec/technical-implementation-spec.md Section 4.

    As of Step 2, this is REITs only - Financial Services (banks) has its own
    real BankAnalyzer engine and is routed there natively, never through this
    error (see check_sector_suitability()'s docstring).

    Unlike DataUnavailableError, this isn't a transient condition - retrying
    won't help, so it's raised outside get_company_data()'s retry loop.
    Callers pass --force to proceed anyway, which never raises this and
    instead threads a warning banner into the generated report.
    """

    def __init__(self, ticker, sector, industry):
        super().__init__(
            f"Ошибка: Тикер {ticker} относится к сектору {sector} ({industry}). "
            "Экспресс-методика и классический DCF не применимы к REIT. "
            "Используйте флаг --force для принудительного запуска."
        )
        self.ticker = ticker
        self.sector = sector
        self.industry = industry
