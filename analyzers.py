"""Analyzer routing skeleton (Step 1 of the methodology upgrade - see
docs/spec/step1-ordinary-router-implementation-spec.md).

Adapter pattern: OrdinaryAnalyzer wraps the existing, tested function-based
engine in financial_analyzer.py (get_company_data/compute_metrics/
build_pdf_report/build_markdown_report) rather than reimplementing it.
BankAnalyzer/ReitAnalyzer are Step-1 stubs that delegate to OrdinaryAnalyzer
under --force, byte-for-byte identical to the sector guardrail's shipped
behavior - see the spec's decision log for why this isn't a "real" rewrite
yet. Bank/REIT-specific checklists and valuation models land in Step 2/3.
"""

from abc import ABC, abstractmethod

from financial_analyzer import (
    build_markdown_report,
    build_pdf_report,
    check_sector_suitability,
    compute_forward_outlook,
    compute_metrics,
    get_company_data,
)


class BaseAnalyzer(ABC):
    """Common interface every sector pipeline implements. The five-method
    shape (fetch/metrics/fair_value/markdown/pdf) is kept uniform across all
    three analyzers for BankAnalyzer/ReitAnalyzer's future real
    implementations - OrdinaryAnalyzer's calculate_fair_value() is a
    pass-through today only because compute_metrics() already bundles the
    sins checklist and the DCF fair value into one call (see its docstring).
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
        """Convenience orchestration for callers that just want the metrics
        dict (e.g. portfolio_analyzer.py) - runs fetch + metrics + fair
        value. Report generation is invoked separately by whichever caller
        actually needs a per-ticker PDF/MD (portfolio_analyzer.py never
        does - it only builds the comparative report)."""
        self.fetch_data()
        self.calculate_metrics()
        self.calculate_fair_value()
        return self.metrics


class OrdinaryAnalyzer(BaseAnalyzer):
    """Adapter over the existing engine - see module docstring."""

    def fetch_data(self):
        self.data = get_company_data(
            self.ticker,
            retries=getattr(self.args, "retries", 5),
            retry_delay=getattr(self.args, "retry_delay", 5),
            allow_sample=getattr(self.args, "allow_sample", False),
        )
        return self.data

    def calculate_metrics(self):
        self.metrics = compute_metrics(
            self.data, required_return=getattr(self.args, "required_return", None)
        )
        return self.metrics

    def calculate_fair_value(self):
        # compute_metrics() already computed the DCF fair value alongside
        # the sins checklist in one pass - nothing further to do here.
        return self.metrics

    def generate_markdown_report(self):
        forward_outlook = compute_forward_outlook(
            self.data.get("info", {}), self.metrics["price"], self.metrics["eps"], self.metrics["cagr"],
        )
        return build_markdown_report(
            self.ticker, self.data, self.metrics, forward_outlook,
            getattr(self.args, "catalysts_text", None),
            getattr(self.args, "excluded_sector", None),
            getattr(self.args, "excluded_industry", None),
        )

    def generate_pdf_report(self):
        # Re-fetches and re-computes internally - an accepted, deliberate
        # seam for Step 1 (see spec Section 1.1); build_pdf_report() isn't
        # split into fetch/render phases in this pass to avoid touching the
        # tested ReportLab layout code.
        return build_pdf_report(
            self.ticker,
            retries=getattr(self.args, "retries", 5),
            retry_delay=getattr(self.args, "retry_delay", 5),
            allow_sample=getattr(self.args, "allow_sample", False),
            catalysts_text=getattr(self.args, "catalysts_text", None),
            force=getattr(self.args, "force", False),
            required_return=getattr(self.args, "required_return", None),
        )


class BankAnalyzer(BaseAnalyzer):
    """Step 1 stub - real NII/DDM/PB-ROE logic is Step 2 scope (not yet
    specified). Delegates every call to an internal OrdinaryAnalyzer,
    unchanged from today's shipped --force behavior: check_sector_suitability()
    (called by AnalyzerFactory before this class is ever instantiated - see
    below) is the single source of truth for the fail-fast-without---force
    behavior, so this class never duplicates that check itself.

    `data`/`metrics` are properties proxying the delegate's own attributes,
    not separate storage - a caller that does `analyzer.data = probe_data`
    (the portfolio_analyzer.py double-fetch optimization, see AnalyzerFactory
    callers) must reach the same object compute_metrics() will actually read
    inside calculate_metrics(), which runs on the delegate, not on self.
    """

    def __init__(self, ticker, args):
        self._delegate = OrdinaryAnalyzer(ticker, args)
        super().__init__(ticker, args)

    @property
    def data(self):
        return self._delegate.data

    @data.setter
    def data(self, value):
        self._delegate.data = value

    @property
    def metrics(self):
        return self._delegate.metrics

    @metrics.setter
    def metrics(self, value):
        self._delegate.metrics = value

    def fetch_data(self):
        return self._delegate.fetch_data()

    def calculate_metrics(self):
        return self._delegate.calculate_metrics()

    def calculate_fair_value(self):
        return self._delegate.calculate_fair_value()

    def generate_markdown_report(self):
        return self._delegate.generate_markdown_report()

    def generate_pdf_report(self):
        return self._delegate.generate_pdf_report()


class ReitAnalyzer(BankAnalyzer):
    """Identical delegation strategy to BankAnalyzer - subclassed purely to
    avoid repeating five one-line delegating methods, not because REIT
    shares any real logic with Banking. Re-parent to BaseAnalyzer directly
    in Step 3 once this gets real NAV/FFO logic that shares nothing with
    BankAnalyzer's future DDM/PB-ROE implementation."""


class AnalyzerFactory:
    @staticmethod
    def get_analyzer(ticker, args, info):
        """Routes to the right analyzer based on `info` (the yfinance .info
        dict for `ticker` - callers fetch this once and pass it in; this
        function never fetches data itself, it only routes).

        Reuses check_sector_suitability() as-is for both the routing
        decision and the fail-fast-without---force behavior - raises
        UnsupportedSectorError (from financial_analyzer.py, unchanged) when
        the sector is restricted and args.force is falsy. Callers catch it
        exactly as they do today.

        Stashes excluded_sector/excluded_industry onto `args` so
        OrdinaryAnalyzer.generate_markdown_report() (and, via delegation,
        Bank/ReitAnalyzer) can thread them into the warning-banner
        rendering without another signature change to build_markdown_report().
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
