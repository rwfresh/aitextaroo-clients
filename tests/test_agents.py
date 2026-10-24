"""Tests for agent abstraction and CLI agent."""

import asyncio
from unittest.mock import patch

import pytest

from aitextaroo.agents import (
    BUILTIN_AGENTS,
    Agent,
    CliAgent,
    CliAgentConfig,
    create_agent,
    custom_agent,
    detect_agents,
)


class TestCliAgentConfig:
    def test_frozen(self) -> None:
        config = CliAgentConfig(name="Test", command="echo")
        with pytest.raises(AttributeError):
            config.name = "changed"  # type: ignore[misc]

    def test_defaults(self) -> None:
        config = CliAgentConfig(name="Test", command="echo")
        assert config.args == []
        assert config.system_prompt == ""
        assert config.timeout == 120


class TestCliAgent:
    @pytest.mark.asyncio
    async def test_ask_returns_stdout(self) -> None:
        config = CliAgentConfig(name="Echo", command="echo", args=[])
        agent = CliAgent(config)
        result = await agent.ask("hello world")
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self) -> None:
        config = CliAgentConfig(name="Slow", command="sleep", args=[], timeout=0.1)
        agent = CliAgent(config)
        with pytest.raises(asyncio.TimeoutError):
            await agent.ask("10")

    @pytest.mark.asyncio
    async def test_nonzero_exit_still_returns_stdout(self) -> None:
        config = CliAgentConfig(name="Fail", command="bash", args=["-c"])
        agent = CliAgent(config)
        result = await agent.ask("echo output; exit 1")
        assert result == "output"

    def test_name_property(self) -> None:
        config = CliAgentConfig(name="My Agent", command="test")
        agent = CliAgent(config)
        assert agent.name == "My Agent"

    def test_system_prompt_property(self) -> None:
        config = CliAgentConfig(name="Test", command="test", system_prompt="Be concise.")
        agent = CliAgent(config)
        assert agent.system_prompt == "Be concise."

    def test_system_prompt_default_empty(self) -> None:
        config = CliAgentConfig(name="Test", command="test")
        agent = CliAgent(config)
        assert agent.system_prompt == ""


class TestAgentInterface:
    def test_agent_is_abstract(self) -> None:
        with pytest.raises(TypeError):
            Agent()  # type: ignore[abstract]

    def test_close_has_default_noop(self) -> None:
        """Agent.close() should have a default implementation (no-op)."""
        # Can't instantiate Agent directly, but we can verify the method exists
        assert hasattr(Agent, "close")

    def test_system_prompt_has_default(self) -> None:
        """Agent.system_prompt should default to empty string."""
        assert Agent.system_prompt.fget is not None  # type: ignore[union-attr]


class TestRegistry:
    def test_create_known_agent(self) -> None:
        agent = create_agent("claude")
        assert agent.name == "Claude Code"

    def test_create_unknown_agent_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown agent"):
            create_agent("nonexistent")

    def test_builtin_agents_all_have_required_fields(self) -> None:
        for name, config in BUILTIN_AGENTS.items():
            assert config.name, f"{name} missing name"
            assert config.command, f"{name} missing command"

    def test_builtin_agents_all_have_system_prompts(self) -> None:
        for name, config in BUILTIN_AGENTS.items():
            assert config.system_prompt, f"{name} missing system_prompt"

    @patch("aitextaroo.agents.shutil.which")
    def test_detect_agents(self, mock_which) -> None:
        mock_which.side_effect = lambda cmd: "/usr/bin/claude" if cmd == "claude" else None
        found = detect_agents()
        assert "claude" in found
        assert "hermes" not in found


class TestOutputFileAgents:
    @pytest.mark.asyncio
    async def test_reads_reply_from_output_file(self) -> None:
        # Mimics `codex exec -o FILE PROMPT`: logs on stdout, answer in FILE.
        script = 'echo "progress log"; printf "final answer" > "$2"'
        config = CliAgentConfig(
            name="FileAgent", command="bash", args=["-c", script, "_"], output_flag="-o"
        )
        assert await CliAgent(config).ask("hello") == "final answer"

    @pytest.mark.asyncio
    async def test_falls_back_to_stdout_when_file_is_empty(self) -> None:
        config = CliAgentConfig(
            name="NoFile", command="bash", args=["-c", 'echo "only stdout"', "_"], output_flag="-o"
        )
        assert await CliAgent(config).ask("hello") == "only stdout"

    @pytest.mark.asyncio
    async def test_prompt_is_last_argument(self) -> None:
        script = 'printf "%s" "$3" > "$2"'
        config = CliAgentConfig(
            name="Echo", command="bash", args=["-c", script, "_"], output_flag="-o"
        )
        assert await CliAgent(config).ask("the prompt") == "the prompt"


class TestBuiltinAgentFlags:
    def test_one_shot_flags(self) -> None:
        assert BUILTIN_AGENTS["claude"].args == ["-p"]
        assert BUILTIN_AGENTS["hermes"].args == ["-z"]
        assert BUILTIN_AGENTS["grok"].args[-1] == "-p"
        assert BUILTIN_AGENTS["openclaw"].args == ["agent", "exec"]
        assert BUILTIN_AGENTS["goose"].args[-1] == "-t"
        assert "nanoclaw" not in BUILTIN_AGENTS
        codex = BUILTIN_AGENTS["codex"]
        assert codex.args[0] == "exec"
        assert codex.output_flag == "-o"

    def test_all_agents_share_the_pin_guidance(self) -> None:
        for name, config in BUILTIN_AGENTS.items():
            assert "PIN" in config.system_prompt, name


class TestCustomAndAmbiguousAgents:
    @patch("aitextaroo.agents.shutil.which")
    def test_ambiguous_binaries_are_not_auto_detected(self, mock_which) -> None:
        mock_which.side_effect = lambda cmd: f"/usr/bin/{cmd}" if cmd == "agent" else None
        assert detect_agents() == []
        assert BUILTIN_AGENTS["cursor"].auto_detect is False

    def test_custom_agent_splits_command_line(self) -> None:
        agent = custom_agent('pnpm --silent --dir "/opt/my claw" run chat')
        assert agent._config.command == "pnpm"
        assert agent._config.args == ["--silent", "--dir", "/opt/my claw", "run", "chat"]
        assert "PIN" in agent.system_prompt

    @pytest.mark.asyncio
    async def test_custom_agent_runs(self) -> None:
        agent = custom_agent("echo replying to")
        assert await agent.ask("hi") == "replying to hi"

    def test_custom_agent_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            custom_agent("   ")
