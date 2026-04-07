"""Tests for SMS formatting."""

from aitextaroo.formatting import format_for_sms


class TestFormatForSms:
    def test_strips_bold(self) -> None:
        assert format_for_sms("This is **bold** text") == "This is bold text"

    def test_strips_italic_asterisk(self) -> None:
        assert format_for_sms("This is *italic* text") == "This is italic text"

    def test_strips_italic_underscore(self) -> None:
        assert format_for_sms("This is _italic_ text") == "This is italic text"

    def test_strips_underline(self) -> None:
        assert format_for_sms("This is __underlined__ text") == "This is underlined text"

    def test_strips_inline_code(self) -> None:
        assert format_for_sms("Run `pip install x`") == "Run pip install x"

    def test_strips_code_blocks(self) -> None:
        text = "Here:\n```python\nprint('hi')\n```\nDone"
        assert format_for_sms(text) == "Here:\nprint('hi')\nDone"

    def test_strips_headers(self) -> None:
        assert format_for_sms("# Title\n## Subtitle") == "Title\nSubtitle"

    def test_strips_links(self) -> None:
        assert format_for_sms("See [this page](https://example.com)") == "See this page"

    def test_strips_horizontal_rules(self) -> None:
        assert format_for_sms("Above\n---\nBelow") == "Above\n\nBelow"

    def test_normalizes_bullet_points(self) -> None:
        text = "* Item one\n+ Item two\n- Item three"
        result = format_for_sms(text)
        assert "- Item one" in result
        assert "- Item two" in result
        assert "- Item three" in result

    def test_collapses_blank_lines(self) -> None:
        assert format_for_sms("A\n\n\n\n\nB") == "A\n\nB"

    def test_strips_whitespace(self) -> None:
        assert format_for_sms("  hello  ") == "hello"

    def test_plain_text_unchanged(self) -> None:
        text = "Just a normal message with no markdown"
        assert format_for_sms(text) == text

    def test_combined_formatting(self) -> None:
        text = "# Hello\n\n**Bold** and *italic* with `code`\n\n---\n\n[link](url)"
        result = format_for_sms(text)
        assert "Hello" in result
        assert "Bold" in result
        assert "italic" in result
        assert "code" in result
        assert "link" in result
        assert "**" not in result
        assert "*" not in result
        assert "`" not in result
        assert "#" not in result
        assert "---" not in result
        assert "[" not in result
