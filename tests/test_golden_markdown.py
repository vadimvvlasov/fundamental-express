"""Golden-output characterization harness (Phase 1, docs/spec/refactor-tasks.md T01).

Feeds hand-built, network-free fixtures (tests/golden/fixtures/*.py) through
compute_*_metrics() + build_*_markdown_report() and diffs the result against
a committed snapshot, byte for byte. Markdown only - PDFs are not
byte-reproducible page to page.

This is the safety net for the rendering refactor in
docs/spec/refactor-architecture-spec.md: once section content moves into
domain/reporting modules, any change to a report's structure or wording
makes one of these three tests fail with a full string diff.
"""

import os
import sys

import financial_analyzer as fa

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "golden", "fixtures"))
from ordinary_data import build_ordinary_data  # noqa: E402
from bank_data import build_bank_data  # noqa: E402
from reit_data import build_reit_data  # noqa: E402

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "golden", "snapshots")


def _read_snapshot(name):
    with open(os.path.join(SNAPSHOT_DIR, name), encoding="utf-8") as f:
        return f.read()


def test_ordinary_golden_markdown(monkeypatch, tmp_path):
    monkeypatch.setattr(fa, "OUTPUT_DIR", str(tmp_path))
    data = build_ordinary_data()
    m = fa.compute_metrics(data)
    forward_outlook = fa.compute_forward_outlook(data.get("info", {}), m.valuation.price, m.eps, m.cagr)
    md_path = fa.build_markdown_report("ACME", data, m, forward_outlook)
    content = open(md_path, encoding="utf-8").read()
    assert content == _read_snapshot("ordinary.md")


def test_bank_golden_markdown(monkeypatch, tmp_path):
    monkeypatch.setattr(fa, "OUTPUT_DIR", str(tmp_path))
    data = build_bank_data()
    m = fa.compute_bank_metrics(data)
    md_path = fa.build_bank_markdown_report("GOLDBANK", data, m)
    content = open(md_path, encoding="utf-8").read()
    assert content == _read_snapshot("bank.md")


def test_reit_golden_markdown(monkeypatch, tmp_path):
    monkeypatch.setattr(fa, "OUTPUT_DIR", str(tmp_path))
    data = build_reit_data()
    m = fa.compute_reit_metrics(data)
    md_path = fa.build_reit_markdown_report("PROPCO", data, m)
    content = open(md_path, encoding="utf-8").read()
    assert content == _read_snapshot("reit.md")
