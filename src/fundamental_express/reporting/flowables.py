"""Custom ReportLab Flowable subclasses shared by every PDF report builder:
a thin section-divider rule, a callout box (accent bar + tint background),
and a louder full-bleed sector-warning banner. Moved verbatim out of
financial_analyzer.py (docs/spec/refactor-tasks.md T03).
"""

from reportlab.platypus import Flowable, Paragraph


# ── FLOWABLE: SECTION DIVIDER ──────────────────────────────────────────
class SectionDivider(Flowable):
    def __init__(self, width, color):
        Flowable.__init__(self)
        self._width = width
        self.color = color
        self._height = 20

    def wrap(self, availWidth, availHeight):
        return self._width, self._height

    def draw(self):
        y = self._height / 2
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(1.2)
        self.canv.line(0, y, self._width, y)


# ── FLOWABLE: CALLOUT BOX ──────────────────────────────────────────────
class CalloutBox(Flowable):
    def __init__(self, text, width, colors, body_style, bar_color=None):
        Flowable.__init__(self)
        self._width = width
        self.colors = colors
        self.bar_color = bar_color or colors["accent"]
        self.bar_w = 6
        self.pad = 10
        inner_w = self._width - self.bar_w - 2 * self.pad
        self._para = Paragraph(text, body_style)
        self._para_w, self._para_h = self._para.wrap(inner_w, 10000)
        self._height = self._para_h + 2 * self.pad

    def wrap(self, availWidth, availHeight):
        return self._width, self._height

    def draw(self):
        self.canv.setFillColor(self.colors["bg_alt"])
        self.canv.rect(0, 0, self._width, self._height, fill=1, stroke=0)
        self.canv.setFillColor(self.bar_color)
        self.canv.rect(0, 0, self.bar_w, self._height, fill=1, stroke=0)
        self._para.drawOn(self.canv, self.bar_w + self.pad, self.pad)


# ── FLOWABLE: SECTOR WARNING BANNER ─────────────────────────────────────
class SectorWarningBanner(Flowable):
    """Full-bleed solid-color banner - deliberately louder than CalloutBox's
    bg_alt-plus-accent-bar style, since a sector-suitability warning (spec
    Section 4.4) needs to read as urgent at a glance, not as routine context.
    """

    def __init__(self, text, width, colors, body_style, fill_color=None):
        Flowable.__init__(self)
        self._width = width
        self.fill_color = fill_color or colors["danger"]
        self.pad = 10
        self._para = Paragraph(text, body_style)
        self._para_w, self._para_h = self._para.wrap(self._width - 2 * self.pad, 10000)
        self._height = self._para_h + 2 * self.pad

    def wrap(self, availWidth, availHeight):
        return self._width, self._height

    def draw(self):
        self.canv.setFillColor(self.fill_color)
        self.canv.rect(0, 0, self._width, self._height, fill=1, stroke=0)
        self._para.drawOn(self.canv, self.pad, self.pad)
