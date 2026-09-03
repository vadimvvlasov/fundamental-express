"""financial_analyzer.py's __main__ argparse block, moved out
(docs/spec/refactor-tasks.md T22). financial_analyzer.py itself keeps
compute_metrics()/etc. - only the CLI entry point moved; financial_analyzer.py's
own `if __name__ == "__main__":` now just calls main() here so
`python financial_analyzer.py <ticker>` keeps working unchanged.

Routes through analyzers.AnalyzerFactory (same probe-fetch-then-route
pattern as cli/portfolio.py's analyze_holdings()) instead of calling a
hardcoded Ordinary build_pdf_report() - that used to send every ticker
through the Ordinary CAPM/WACC FCF-DCF regardless of sector, silently
giving a Financial Services/REIT ticker a fair value from a model that
doesn't fit its balance sheet (EV/Net Debt/FCF aren't meaningful for a
bank) instead of its real DDM/ROE-P-B or NAV model. Routing through the
same factory portfolio.py uses keeps both entry points agreeing on which
model a given ticker gets.
"""

import argparse

from analyzers import AnalyzerFactory
from financial_analyzer import DataUnavailableError, UnsupportedSectorError, get_company_data
from fundamental_express.cli.args import required_return_type
from fundamental_express.cli.catalysts import resolve_catalysts_text


def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive Fundamental Express Analyzer & DCF Model"
    )
    parser.add_argument(
        "ticker", type=str, nargs="?", default="AAPL",
        help="Stock ticker symbol (e.g. AAPL, MSFT, TSLA)",
    )
    parser.add_argument(
        "--retries", type=int, default=5,
        help="How many times to retry Yahoo Finance before giving up (default 5)",
    )
    parser.add_argument(
        "--retry-delay", type=int, default=5,
        help="Seconds to wait between retries (default 5)",
    )
    parser.add_argument(
        "--allow-sample", action="store_true",
        help="Fall back to labeled SAMPLE data if real data can't be fetched (demo only, off by default)",
    )
    parser.add_argument(
        "--catalysts", type=str, default=None,
        help="Free-text note on catalysts/risks to embed in the report (e.g. product launch, regulatory event).",
    )
    parser.add_argument(
        "--catalysts-file", type=str, default=None,
        help="Path to a text file with the catalysts note (alternative to --catalysts).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Принудительно запустить анализ для несовместимых секторов (Финансы/REIT) под ответственность пользователя.",
    )
    parser.add_argument(
        "--required-return", type=required_return_type, default=None,
        help="Персональная требуемая доходность инвестора (0.05-0.25), заменяет CAPM-расчёт Ke.",
    )
    args = parser.parse_args()

    args.catalysts_text = resolve_catalysts_text(args.catalysts, args.catalysts_file)
    ticker = args.ticker

    try:
        # One fetch to get `info` for AnalyzerFactory's routing decision -
        # analyzer.data is set directly from it below instead of calling
        # analyzer.fetch_data(), which would trigger a wasteful second full
        # fetch of the same ticker (mirrors cli/portfolio.py's pattern).
        data = get_company_data(
            ticker, retries=args.retries, retry_delay=args.retry_delay, allow_sample=args.allow_sample,
        )
        analyzer = AnalyzerFactory.get_analyzer(ticker, args, data.get("info", {}))
        analyzer.data = data
        analyzer.calculate_metrics()
        analyzer.calculate_fair_value()

        pdf_filename = analyzer.generate_pdf_report()
        print(f"Success! Comprehensive report saved to: {pdf_filename}")

        md_filename = analyzer.generate_markdown_report()
        print(f"Success! Markdown report saved to: {md_filename}")
    except DataUnavailableError as e:
        print(f"FAILED: {e}")
        raise SystemExit(1)
    except UnsupportedSectorError as e:
        print(str(e))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
