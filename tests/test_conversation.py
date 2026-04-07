"""Tests for conversation history."""

from aitextaroo.conversation import Conversation


class TestConversation:
    def test_starts_empty(self) -> None:
        conv = Conversation()
        assert conv.is_empty
        assert conv.count == 0

    def test_add_user_message(self) -> None:
        conv = Conversation()
        conv.add_user_message("hello")
        assert conv.count == 1
        assert conv.messages[0].role == "user"
        assert conv.messages[0].text == "hello"

    def test_add_assistant_message(self) -> None:
        conv = Conversation()
        conv.add_assistant_message("hi back")
        assert conv.count == 1
        assert conv.messages[0].role == "assistant"

    def test_clear(self) -> None:
        conv = Conversation()
        conv.add_user_message("hello")
        conv.add_assistant_message("hi")
        conv.clear()
        assert conv.is_empty

    def test_prunes_oldest_when_full(self) -> None:
        conv = Conversation(max_messages=3)
        conv.add_user_message("first")
        conv.add_assistant_message("second")
        conv.add_user_message("third")
        conv.add_assistant_message("fourth")
        assert conv.count == 3
        # "first" should be pruned
        assert conv.messages[0].text == "second"

    def test_messages_returns_copy(self) -> None:
        conv = Conversation()
        conv.add_user_message("hello")
        msgs = conv.messages
        msgs.clear()
        # Original should be unaffected
        assert conv.count == 1

    def test_format_empty_returns_empty_string(self) -> None:
        conv = Conversation()
        assert conv.format_as_context() == ""

    def test_format_as_context(self) -> None:
        conv = Conversation()
        conv.add_user_message("Hey")
        conv.add_assistant_message("Hi there!")
        conv.add_user_message("How are you?")

        result = conv.format_as_context()
        assert "[Conversation history]" in result
        assert "User: Hey" in result
        assert "Assistant: Hi there!" in result
        assert "User: How are you?" in result

    def test_format_preserves_order(self) -> None:
        conv = Conversation()
        conv.add_user_message("A")
        conv.add_assistant_message("B")
        conv.add_user_message("C")

        lines = conv.format_as_context().split("\n")
        # Skip header line
        assert lines[1] == "User: A"
        assert lines[2] == "Assistant: B"
        assert lines[3] == "User: C"
