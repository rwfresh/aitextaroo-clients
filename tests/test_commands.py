"""Tests for command routing."""

from aitextaroo.commands import CommandRouter
from aitextaroo.conversation import Conversation


def _make_router(agent_name: str = "TestAgent") -> CommandRouter:
    conv = Conversation()
    return CommandRouter(agent_name=agent_name, conversation=conv, start_time=0)


class TestCommandRouter:
    def test_is_command_with_slash(self) -> None:
        router = _make_router()
        assert router.is_command("/help") is True
        assert router.is_command("/new") is True

    def test_is_not_command_without_slash(self) -> None:
        router = _make_router()
        assert router.is_command("hello") is False
        assert router.is_command("") is False

    def test_is_not_command_slash_only(self) -> None:
        router = _make_router()
        assert router.is_command("/") is False

    def test_help_lists_commands(self) -> None:
        router = _make_router()
        result = router.handle("/help")
        assert "/help" in result
        assert "/new" in result
        assert "/status" in result

    def test_new_clears_conversation(self) -> None:
        conv = Conversation()
        conv.add_user_message("hello")
        conv.add_assistant_message("hi")
        router = CommandRouter(agent_name="Test", conversation=conv)

        result = router.handle("/new")
        assert "cleared" in result.lower() or "fresh" in result.lower()
        assert conv.is_empty

    def test_status_shows_agent_name(self) -> None:
        router = _make_router(agent_name="Claude Code")
        result = router.handle("/status")
        assert "Claude Code" in result

    def test_status_shows_message_count(self) -> None:
        router = _make_router()
        router.increment_message_count()
        router.increment_message_count()
        result = router.handle("/status")
        assert "2" in result

    def test_status_shows_history_count(self) -> None:
        conv = Conversation()
        conv.add_user_message("hello")
        conv.add_assistant_message("hi")
        router = CommandRouter(agent_name="Test", conversation=conv)
        result = router.handle("/status")
        assert "2" in result

    def test_unknown_command(self) -> None:
        router = _make_router()
        result = router.handle("/unknown")
        assert "unknown" in result.lower()
        assert "/help" in result

    def test_case_insensitive(self) -> None:
        router = _make_router()
        result = router.handle("/HELP")
        assert "/help" in result

    def test_command_with_extra_text(self) -> None:
        router = _make_router()
        # /new with trailing text should still work
        result = router.handle("/new please")
        assert conv_cleared_or_fresh(result)

    def test_increment_message_count(self) -> None:
        router = _make_router()
        assert router.message_count == 0
        router.increment_message_count()
        assert router.message_count == 1


def conv_cleared_or_fresh(text: str) -> bool:
    lower = text.lower()
    return "cleared" in lower or "fresh" in lower
