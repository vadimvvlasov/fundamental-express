"""financial_analyzer.py's __main__ argparse block, moved out
(docs/spec/refactor-tasks.md T22). financial_analyzer.py itself keeps
compute_metrics()/build_pdf_report()/etc. - only the CLI entry point moved;
financial_analyzer.py's own `if __name__ == "__main__":` now just calls
main() here so `python financial_analyzer.py <ticker>` keeps working
unchanged.
"""

import argparse

from financial_analyzer import build_pdf_report, DataUnavailableError, UnsupportedSectorError
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

    catalysts_text = resolve_catalysts_text(args.catalysts, args.catalysts_file)

    try:
        build_pdf_report(
            args.ticker, retries=args.retries, retry_delay=args.retry_delay,
            allow_sample=args.allow_sample, catalysts_text=catalysts_text, force=args.force,
            required_return=args.required_return,
        )
    except DataUnavailableError as e:
        print(f"FAILED: {e}")
        raise SystemExit(1)
    except UnsupportedSectorError as e:
        print(str(e))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
