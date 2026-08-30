"""Workspace path constants. Moved verbatim out of financial_analyzer.py
(docs/spec/refactor-tasks.md T22).
"""

import os
from pathlib import Path

# src/fundamental_express/cli/paths.py -> repo root is 3 parents up.
SCRIPT_DIR = str(Path(__file__).resolve().parents[3])
SCRATCH_DIR = os.path.join(SCRIPT_DIR, "scratch")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
os.makedirs(SCRATCH_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
