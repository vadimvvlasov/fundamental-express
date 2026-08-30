"""Visual theme shared by every PDF/Markdown report: colors, Unicode fonts,
page geometry, and the two tiny formatting helpers (`escape_xml`,
`_fmt_or_na`) every renderer calls. Zero knowledge of any asset class or
report structure - moved verbatim out of financial_analyzer.py
(docs/spec/refactor-tasks.md T02).
"""

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── DESIGN PALETTE (Corporate Slate & Teal Archetype) ──────────────────
COLORS = {
    "heading": HexColor("#1E293B"),  # Deep Slate - titles & sections
    "body": HexColor("#334155"),  # Slate - readable text
    "accent": HexColor("#0F766E"),  # Teal - visual highlights/underlines
    "muted": HexColor("#64748B"),  # Slate gray - headers, page numbers
    "bg_alt": HexColor("#F8FAFC"),  # Off-white tint - tables, callouts
    "bg_header": HexColor("#0F766E"),  # Teal - table header backgrounds
    "white": HexColor("#FFFFFF"),
    "success": HexColor("#16A34A"),  # Green for positive indicators
    "danger": HexColor("#DC2626"),  # Red for warning flags
    "warning": HexColor("#D97706"),  # Amber for cautionary notes
}

# ── REGISTER UNICODE FONTS ──────────────────────────────────────────────
# We look for DejaVuSans because it natively supports Cyrillic characters.
try:
    pdfmetrics.registerFont(
        TTFont("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    )
    pdfmetrics.registerFont(
        TTFont(
            "DejaVuSans-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        )
    )
    pdfmetrics.registerFontFamily(
        "DejaVuSans", normal="DejaVuSans", bold="DejaVuSans-Bold"
    )
    FONT_NAME = "DejaVuSans"
    FONT_BOLD = "DejaVuSans-Bold"
except Exception as e:
    print(
        f"Warning: Could not register DejaVuSans font: {e}. Falling back to standard Helvetica."
    )
    FONT_NAME = "Helvetica"
    FONT_BOLD = "Helvetica-Bold"

# ── PAGE GEOMETRY ───────────────────────────────────────────────────────
PAGE_SIZE = LETTER
MARGIN = 0.75 * inch  # 54pt for clean layout and compact tables
PAGE_W, PAGE_H = PAGE_SIZE
USABLE_W = PAGE_W - 2 * MARGIN


# ── HELPER: ESCAPE XML SYMBOLS FOR PARAGRAPH ────────────────────────────
def escape_xml(val):
    if not isinstance(val, str):
        val = str(val)
    return val.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_or_na(value, fmt="{:.2f}"):
    return fmt.format(value) if value is not None else "N/A"
