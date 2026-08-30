"""Shared section contract (docs/spec/refactor-tasks.md T17,
docs/spec/refactor-architecture-spec.md Section 5).

A `Section` is one numbered block of a report ("## 1. ...", "## 2. ...").
Each asset class's `sections_{ordinary,bank,reit}.py` builds an ordered
`list[Section]` from its own metrics dataclass; a future shared renderer
(`reporting/markdown.py`/`reporting/pdf.py`, T19/T20) will render the
title/header/footer once and loop over this list for the body, instead of
each of the six current build_*_report() functions hand-assembling the
same skeleton with different field names.

Pure content contract - no knowledge of any asset class, no I/O.
"""

from dataclasses import dataclass
from typing import Callable, List


@dataclass(frozen=True)
class Section:
    title: str
    markdown: Callable[[], str]
    flowables: Callable[[], list]


SectionList = List[Section]
