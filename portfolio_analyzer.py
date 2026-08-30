"""Multi-company comparative report CLI. Moved to
src/fundamental_express/cli/portfolio.py (docs/spec/refactor-tasks.md T22) -
this file is now just the entry point that keeps
`python portfolio_analyzer.py <holdings>` working unchanged.
"""

import financial_analyzer  # noqa: F401
# financial_analyzer's import above adds src/ to sys.path as a side effect
# (docs/spec/refactor-tasks.md T02), which this import relies on - same
# pattern documented in analyzers.py.
from fundamental_express.cli.portfolio import main  # noqa: E402

if __name__ == "__main__":
    main()
