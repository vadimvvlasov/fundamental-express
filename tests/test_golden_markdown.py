"""Golden-output characterization harness (Phase 1, docs/spec/refactor-tasks.md T01;
wired onto the unified renderer in T19).

Feeds hand-built, network-free fixtures (tests/golden/fixtures/*.py) through
compute_*_metrics() + the section builders + reporting/markdown.py::render()
and diffs the result against a committed snapshot, byte for byte. Markdown
only - PDFs are not byte-reproducible page to page.

This is the safety net for the rendering refactor in
docs/spec/refactor-architecture-spec.md: any change to a report's
structure or wording makes one of these three tests fail with a full
string diff.
"""

import os
import sys

import financial_analyzer as fa

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden", "fixtures"))
from ordinary_data import build_ordinary_data  # noqa: E402
from bank_data import build_bank_data  # noqa: E402
from reit_data import build_reit_data  # noqa: E402

from fundamental_express.reporting.markdown import render, write  # noqa: E402
from fundamental_express.reporting.sections_ordinary import build_ordinary_sections  # noqa: E402
from fundamental_express.reporting.sections_bank import build_bank_sections  # noqa: E402
from fundamental_express.reporting.sections_reit import build_reit_sections  # noqa: E402

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "golden", "snapshots")


def _read_snapshot(name):
    with open(os.path.join(SNAPSHOT_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_ordinary_golden_markdown(tmp_path):
    data = build_ordinary_data()
    m = fa.compute_metrics(data)
    forward_outlook = fa.compute_forward_outlook(data.get("info", {}), m.valuation.price, m.eps, m.cagr)
    sections = build_ordinary_sections(
        m, forward_outlook, fa.CATALYSTS_PLACEHOLDER,
        data["trading_currency"], data["price_kind"], data["quote_time_label"], "ACME",
    )
    content = render("ACME", data, m, sections)
    md_path = write("ACME", content, str(tmp_path))
    assert open(md_path, encoding="utf-8").read() == _read_snapshot("ordinary.md")


def test_bank_golden_markdown(tmp_path):
    data = build_bank_data()
    m = fa.compute_bank_metrics(data)
    sections = build_bank_sections(
        m, fa.CATALYSTS_PLACEHOLDER, data["trading_currency"], data["price_kind"], data["quote_time_label"], "GOLDBANK",
    )
    content = render("GOLDBANK", data, m, sections)
    md_path = write("GOLDBANK", content, str(tmp_path))
    assert open(md_path, encoding="utf-8").read() == _read_snapshot("bank.md")


def test_reit_golden_markdown(tmp_path):
    data = build_reit_data()
    m = fa.compute_reit_metrics(data)
    sections = build_reit_sections(
        m, fa.CATALYSTS_PLACEHOLDER, data["trading_currency"], data["price_kind"], data["quote_time_label"], "PROPCO",
    )
    content = render("PROPCO", data, m, sections)
    md_path = write("PROPCO", content, str(tmp_path))
    assert open(md_path, encoding="utf-8").read() == _read_snapshot("reit.md")
