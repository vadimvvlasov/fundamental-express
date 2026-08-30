"""Shared ReportLab table builder used by every PDF report. Moved verbatim
out of financial_analyzer.py (docs/spec/refactor-tasks.md T04).
"""

from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle

from fundamental_express.reporting.theme import FONT_NAME, FONT_BOLD, escape_xml


# ── GENERATE EXCEL-STYLE TABLES WITH PARAGRAPHCELLS ────────────────────
def create_reportlab_table(headers, rows, styles, colors, col_widths=None):
    header_style = ParagraphStyle(
        "TableHead",
        fontName=FONT_BOLD,
        fontSize=9,
        textColor=colors["white"],
        leading=11,
    )
    cell_style = ParagraphStyle(
        "TableCell",
        fontName=FONT_NAME,
        fontSize=8.5,
        textColor=colors["body"],
        leading=11,
    )

    header_row = [Paragraph(escape_xml(h), header_style) for h in headers]
    data_rows = []
    for r in rows:
        data_rows.append([Paragraph(escape_xml(str(cell)), cell_style) for cell in r])

    t = Table([header_row] + data_rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors["bg_header"]),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors["white"], colors["bg_alt"]],
                ),
                ("GRID", (0, 0), (-1, -1), 0.5, colors["muted"]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return t
