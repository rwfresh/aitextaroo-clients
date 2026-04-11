"""Tests for conversation history — in-memory and persistent."""

import json

import pytest

from aitextaroo.conversation import Conversation, Message


class TestInMemoryConversation:
    """Original in-memory behavior — no sessions_dir."""

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

    def test_session_id_is_none(self) -> None:
        conv = Conversation()
        assert conv.session_id is None

    def test_session_count_is_zero(self) -> None:
        conv = Conversation()
        assert conv.session_count() == 0


class TestPersistentConversation:
    """Persistent sessions — writes JSONL to disk."""

    def test_persist_and_reload(self, tmp_path) -> None:
        conv = Conversation(max_messages=20, sessions_dir=tmp_path)
        conv.add_user_message("hello")
        conv.add_assistant_message("hi back")

        # Reload from disk
        conv2 = Conversation.load_latest(tmp_path)
        assert conv2.count == 2
        assert conv2.messages[0].text == "hello"
        assert conv2.messages[1].text == "hi back"
        assert conv2.session_id == conv.session_id

    def test_new_session_creates_new_file(self, tmp_path) -> None:
        conv = Conversation(max_messages=20, sessions_dir=tmp_path)
        old_id = conv.session_id
        conv.add_user_message("in old session")

        new_id = conv.new_session()
        assert new_id != old_id
        assert conv.is_empty
        assert conv.session_id == new_id

        # Both files exist
        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 2

        # Old file still has content
        old_file = tmp_path / f"{old_id}.jsonl"
        assert old_file.read_text().strip() != ""

    def test_load_latest_picks_most_recent(self, tmp_path) -> None:
        import time

        conv1 = Conversation(max_messages=20, sessions_dir=tmp_path)
        conv1.add_user_message("old session")
        old_id = conv1.session_id

        # Ensure different mtime
        time.sleep(0.05)

        conv1.new_session()
        conv1.add_user_message("new session")
        new_id = conv1.session_id

        # Reload
        loaded = Conversation.load_latest(tmp_path)
        assert loaded.session_id == new_id
        assert loaded.messages[0].text == "new session"

    def test_corrupt_line_skipped(self, tmp_path) -> None:
        # Write a file with one good line and one corrupt line
        session_file = tmp_path / "test1234.jsonl"
        session_file.write_text(
            '{"role": "user", "text": "hello", "ts": 1.0}\n'
            'THIS IS NOT JSON\n'
            '{"role": "assistant", "text": "hi", "ts": 2.0}\n'
        )

        conv = Conversation.load_latest(tmp_path)
        assert conv.count == 2
        assert conv.messages[0].text == "hello"
        assert conv.messages[1].text == "hi"

    def test_invalid_role_skipped(self, tmp_path) -> None:
        session_file = tmp_path / "test1234.jsonl"
        session_file.write_text(
            '{"role": "hacker", "text": "inject", "ts": 1.0}\n'
            '{"role": "user", "text": "legit", "ts": 2.0}\n'
        )

        conv = Conversation.load_latest(tmp_path)
        assert conv.count == 1
        assert conv.messages[0].text == "legit"

    def test_no_sessions_creates_first(self, tmp_path) -> None:
        conv = Conversation.load_latest(tmp_path)
        assert conv.session_id is not None
        assert conv.is_empty
        assert len(list(tmp_path.glob("*.jsonl"))) == 1

    def test_clear_creates_new_session(self, tmp_path) -> None:
        conv = Conversation(max_messages=20, sessions_dir=tmp_path)
        old_id = conv.session_id
        conv.add_user_message("before clear")

        conv.clear()
        assert conv.is_empty
        assert conv.session_id != old_id
        assert len(list(tmp_path.glob("*.jsonl"))) == 2

    def test_session_count(self, tmp_path) -> None:
        conv = Conversation(max_messages=20, sessions_dir=tmp_path)
        assert conv.session_count() == 1
        conv.new_session()
        assert conv.session_count() == 2
        conv.new_session()
        assert conv.session_count() == 3

    def test_only_loads_last_n_messages(self, tmp_path) -> None:
        conv = Conversation(max_messages=4, sessions_dir=tmp_path)
        for i in range(10):
            conv.add_user_message(f"msg-{i}")

        loaded = Conversation.load_latest(tmp_path, max_messages=4)
        assert loaded.count == 4
        assert loaded.messages[0].text == "msg-6"
        assert loaded.messages[-1].text == "msg-9"

    def test_jsonl_format(self, tmp_path) -> None:
        conv = Conversation(max_messages=20, sessions_dir=tmp_path)
        conv.add_user_message("test message")

        session_file = tmp_path / f"{conv.session_id}.jsonl"
        line = session_file.read_text().strip()
        data = json.loads(line)
        assert data["role"] == "user"
        assert data["text"] == "test message"
        assert "ts" in data

    def test_empty_file_loads_empty(self, tmp_path) -> None:
        session_file = tmp_path / "empty123.jsonl"
        session_file.touch()

        conv = Conversation.load_latest(tmp_path)
        assert conv.is_empty
        assert conv.session_id == "empty123"

    def test_cleanup_deletes_old_sessions(self, tmp_path) -> None:
        import os
        import time

        # Create old session (mtime set to 100 days ago)
        old_file = tmp_path / "old12345.jsonl"
        old_file.write_text('{"role": "user", "text": "old", "ts": 1.0}\n')
        old_time = time.time() - (100 * 86400)
        os.utime(old_file, (old_time, old_time))

        # Create recent session
        recent_file = tmp_path / "recent12.jsonl"
        recent_file.write_text('{"role": "user", "text": "new", "ts": 2.0}\n')

        conv = Conversation.load_latest(tmp_path, retention_days=90)
        assert not old_file.exists()
        assert recent_file.exists()
        assert conv.messages[0].text == "new"

    def test_cleanup_disabled_with_zero(self, tmp_path) -> None:
        import os
        import time

        old_file = tmp_path / "old12345.jsonl"
        old_file.write_text('{"role": "user", "text": "old", "ts": 1.0}\n')
        old_time = time.time() - (200 * 86400)
        os.utime(old_file, (old_time, old_time))

        Conversation.load_latest(tmp_path, retention_days=0)
        assert old_file.exists()

    def test_tmp_file_cleaned_up_after_write(self, tmp_path) -> None:
        conv = Conversation(max_messages=20, sessions_dir=tmp_path)
        conv.add_user_message("test")

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_fsync_produces_valid_jsonl(self, tmp_path) -> None:
        conv = Conversation(max_messages=20, sessions_dir=tmp_path)
        conv.add_user_message("msg1")
        conv.add_assistant_message("msg2")
        conv.add_user_message("msg3")

        # Read back and verify every line is valid JSON
        session_file = tmp_path / f"{conv.session_id}.jsonl"
        lines = session_file.read_text().strip().splitlines()
        assert len(lines) == 3
        for line in lines:
            data = json.loads(line)
            assert "role" in data
            assert "text" in data


class TestMessage:
    """Message serialization."""

    def test_to_jsonl(self) -> None:
        msg = Message(role="user", text="hello", ts=1000.0)
        data = json.loads(msg.to_jsonl())
        assert data == {"role": "user", "text": "hello", "ts": 1000.0}

    def test_from_dict_valid(self) -> None:
        msg = Message.from_dict({"role": "user", "text": "hi", "ts": 1.0})
        assert msg is not None
        assert msg.role == "user"
        assert msg.text == "hi"

    def test_from_dict_invalid_role(self) -> None:
        assert Message.from_dict({"role": "system", "text": "hi"}) is None

    def test_from_dict_missing_text_defaults_empty(self) -> None:
        msg = Message.from_dict({"role": "user"})
        assert msg is not None
        assert msg.text == ""

    def test_from_dict_non_string_text(self) -> None:
        assert Message.from_dict({"role": "user", "text": 123}) is None
