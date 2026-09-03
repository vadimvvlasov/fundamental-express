"""pdf_safe() - DejaVuSans.ttf (the PDF font, theme.py) has no glyph for
🟢/🟡/🔴 (Unicode 12's "large colored circle" emoji) - ReportLab draws an
empty box for them. Markdown output is untouched; only PDF text needs
routing through this first.
"""

from fundamental_express.reporting.theme import pdf_safe


def test_replaces_all_three_verdict_emoji():
    assert pdf_safe("🟢 КУПИТЬ") == "● КУПИТЬ"
    assert pdf_safe("🟡 НАБЛЮДАТЬ") == "● НАБЛЮДАТЬ"
    assert pdf_safe("🔴 ПРОПУСТИТЬ") == "● ПРОПУСТИТЬ"


def test_leaves_text_without_those_emoji_untouched():
    assert pdf_safe("plain text, no emoji") == "plain text, no emoji"
    assert pdf_safe("⚠️ warning sign is fine, stays as-is") == "⚠️ warning sign is fine, stays as-is"
    assert pdf_safe("⚪ muted circle is fine too") == "⚪ muted circle is fine too"


def test_replaces_every_occurrence_not_just_the_first():
    assert pdf_safe("🟢🟢🔴") == "●●●"
