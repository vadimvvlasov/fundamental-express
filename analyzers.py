"""Analyzer routing (Steps 1-3 - see docs/spec/step1-ordinary-router-
implementation-spec.md, docs/spec/step2-bank-analyzer-implementation-spec.md,
docs/spec/step3-reit-analyzer-implementation-spec.md).

Adapter pattern: OrdinaryAnalyzer wraps the existing, tested function-based
engine in financial_analyzer.py (get_company_data/compute_metrics/
build_pdf_report) and the shared markdown renderer (reporting/markdown.py,
reporting/sections_ordinary.py) rather than reimplementing it.
BankAnalyzer (Step 2) and ReitAnalyzer (Step 3) are both real, independent
implementations on top of their own compute_*_metrics()/build_*_report()
engines - neither delegates to OrdinaryAnalyzer anymore.
"""

from abc import ABC, abstractmethod

from financial_analyzer import (
    build_bank_pdf_report,
    build_pdf_report,
    build_reit_pdf_report,
    check_sector_suitability,
    compute_bank_metrics,
    compute_forward_outlook,
    compute_metrics,
    compute_reit_metrics,
    get_company_data,
)
# financial_analyzer's import above adds src/ to sys.path as a side effect
# (docs/spec/refactor-tasks.md T02), which this import relies on.
from fundamental_express.domain.routing import _is_reit  # noqa: E402
from fundamental_express.reporting.markdown import render as md_render, write as md_write  # noqa: E402
from fundamental_express.reporting.sections_ordinary import build_ordinary_sections  # noqa: E402
from fundamental_express.reporting.sections_bank import build_bank_sections  # noqa: E402
from fundamental_express.reporting.sections_reit import build_reit_sections  # noqa: E402
from financial_analyzer import OUTPUT_DIR, CATALYSTS_PLACEHOLDER  # noqa: E402


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
            self.data.get("info", {}), self.metrics.valuation.price, self.metrics.eps, self.metrics.cagr,
        )
        sections = build_ordinary_sections(
            self.metrics, forward_outlook, getattr(self.args, "catalysts_text", None) or CATALYSTS_PLACEHOLDER,
            self.data.get("trading_currency", "USD"), self.data["price_kind"], self.data["quote_time_label"],
        )
        content = md_render(
            self.ticker, self.data, self.metrics, sections,
            getattr(self.args, "excluded_sector", None),
            getattr(self.args, "excluded_industry", None),
        )
        return md_write(self.ticker, content, OUTPUT_DIR)

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
    """Step 2 real implementation - NII/LTD sins checklist and DDM/ROE-P-B
    fair value (compute_bank_metrics()), rendered by the dedicated
    build_bank_pdf_report()/reporting/markdown.py::render() (spec Section 6).
    No longer delegates to OrdinaryAnalyzer: check_sector_suitability() no
    longer restricts Financial Services at all (see its docstring), and
    AnalyzerFactory routes "Financial Services" here unconditionally, with
    or without --force (spec Section 2.1.2 - the flag is accepted but
    no longer required or checked by this class).
    """

    def calculate_fair_value(self):
        # compute_bank_metrics() already computed the DDM/ROE-P-B fair value
        # alongside the sins checklist in one pass - nothing further to do.
        return self.metrics

    def fetch_data(self):
        self.data = get_company_data(
            self.ticker,
            retries=getattr(self.args, "retries", 5),
            retry_delay=getattr(self.args, "retry_delay", 5),
            allow_sample=getattr(self.args, "allow_sample", False),
        )
        return self.data

    def calculate_metrics(self):
        self.metrics = compute_bank_metrics(
            self.data, required_return=getattr(self.args, "required_return", None)
        )
        return self.metrics

    def generate_markdown_report(self):
        sections = build_bank_sections(
            self.metrics, getattr(self.args, "catalysts_text", None) or CATALYSTS_PLACEHOLDER,
            self.data.get("trading_currency", "USD"), self.data["price_kind"], self.data["quote_time_label"],
        )
        content = md_render(self.ticker, self.data, self.metrics, sections)
        return md_write(self.ticker, content, OUTPUT_DIR)

    def generate_pdf_report(self):
        # Re-fetches and re-computes internally, same accepted seam as
        # OrdinaryAnalyzer.generate_pdf_report() (see its docstring).
        return build_bank_pdf_report(
            self.ticker,
            retries=getattr(self.args, "retries", 5),
            retry_delay=getattr(self.args, "retry_delay", 5),
            allow_sample=getattr(self.args, "allow_sample", False),
            catalysts_text=getattr(self.args, "catalysts_text", None),
            required_return=getattr(self.args, "required_return", None),
        )


class ReitAnalyzer(BaseAnalyzer):
    """Step 3 real implementation - FFO/AFFO/NOI sins checklist and NAV fair
    value (compute_reit_metrics()), rendered by the dedicated
    build_reit_pdf_report()/reporting/markdown.py::render() (spec Section 6).
    No longer delegates to OrdinaryAnalyzer: check_sector_suitability() no
    longer restricts any sector at all (see its docstring), and
    AnalyzerFactory routes REIT industries here unconditionally, with or
    without --force (spec Section 7.1.4 - the flag is accepted but has no
    effect on this class), mirroring BankAnalyzer's Step 2 routing.
    """

    def calculate_fair_value(self):
        # compute_reit_metrics() already computed the NAV fair value
        # alongside the sins checklist in one pass - nothing further to do.
        return self.metrics

    def fetch_data(self):
        self.data = get_company_data(
            self.ticker,
            retries=getattr(self.args, "retries", 5),
            retry_delay=getattr(self.args, "retry_delay", 5),
            allow_sample=getattr(self.args, "allow_sample", False),
        )
        return self.data

    def calculate_metrics(self):
        self.metrics = compute_reit_metrics(
            self.data, required_return=getattr(self.args, "required_return", None)
        )
        return self.metrics

    def generate_markdown_report(self):
        sections = build_reit_sections(
            self.metrics, getattr(self.args, "catalysts_text", None) or CATALYSTS_PLACEHOLDER,
            self.data.get("trading_currency", "USD"), self.data["price_kind"], self.data["quote_time_label"],
        )
        content = md_render(self.ticker, self.data, self.metrics, sections)
        return md_write(self.ticker, content, OUTPUT_DIR)

    def generate_pdf_report(self):
        # Re-fetches and re-computes internally, same accepted seam as
        # OrdinaryAnalyzer.generate_pdf_report() (see its docstring).
        return build_reit_pdf_report(
            self.ticker,
            retries=getattr(self.args, "retries", 5),
            retry_delay=getattr(self.args, "retry_delay", 5),
            allow_sample=getattr(self.args, "allow_sample", False),
            catalysts_text=getattr(self.args, "catalysts_text", None),
            required_return=getattr(self.args, "required_return", None),
        )


class AnalyzerFactory:
    @staticmethod
    def get_analyzer(ticker, args, info):
        """Routes to the right analyzer based on `info` (the yfinance .info
        dict for `ticker` - callers fetch this once and pass it in; this
        function never fetches data itself, it only routes).

        Financial Services (banks, Step 2) and REIT industries (Step 3) are
        both routed to their real analyzers unconditionally, before
        check_sector_suitability() is even called - neither needs a --force
        gate or a warning-banner path anymore, since both got dedicated
        specialized engines. --force is still accepted for either (backward
        compatibility) but has no effect on these two branches.

        Every remaining ticker falls through to check_sector_suitability(),
        which as of Step 3 never restricts anything (see its docstring) -
        kept in place only so a future sector can reuse the same mechanism,
        and so OrdinaryAnalyzer's warning-banner rendering path in
        reporting/markdown.py::render()/build_pdf_report() stays exercised
        by its existing tests even though no live sector currently
        triggers it.

        Stashes excluded_sector/excluded_industry onto `args` so
        OrdinaryAnalyzer.generate_markdown_report() can thread them into
        render()'s warning-banner rendering without another signature
        change. Set to None for the bank/REIT branches, which never carry
        that warning banner.
        """
        sector = info.get("sector") or ""
        if sector == "Financial Services":
            args.excluded_sector = None
            args.excluded_industry = None
            return BankAnalyzer(ticker, args)

        if _is_reit(info):
            args.excluded_sector = None
            args.excluded_industry = None
            return ReitAnalyzer(ticker, args)

        force = getattr(args, "force", False)
        excluded_sector, excluded_industry = check_sector_suitability(ticker, info, force)
        args.excluded_sector = excluded_sector
        args.excluded_industry = excluded_industry
        return OrdinaryAnalyzer(ticker, args)
