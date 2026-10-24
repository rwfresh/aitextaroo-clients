"""Agent abstraction for the AI Text-a-roo bridge.

Defines how the bridge communicates with AI agents. Each agent
takes a text message in and produces a text response.

The only implementation today is CliAgent — a one-shot subprocess
invocation per message. New agent types (HTTP API, long-running
process, etc.) can be added by implementing the Agent protocol.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Maximum time to wait for an agent to respond (seconds).
DEFAULT_TIMEOUT = 120


class Agent(ABC):
    """Interface for an AI agent that processes text messages.

    Implementations must be able to:
    1. Accept a text prompt and return a text response.
    2. Provide a display name and optional system prompt.
    3. Release any held resources on close.

    The bridge reads system_prompt to build conversation context.
    The agent receives the fully-assembled prompt — it does not
    need to manage conversation state or system instructions.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for display and logging."""

    @property
    def system_prompt(self) -> str:
        """System instructions prepended to every prompt by the bridge.

        Override to provide agent-specific context (e.g., "respond
        concisely, these are SMS messages"). Default is empty.
        """
        return ""

    @abstractmethod
    async def ask(self, text: str) -> str:
        """Send a fully-assembled prompt and return the response.

        The prompt already includes system instructions and
        conversation history (assembled by the bridge). The agent
        just needs to run it.

        Args:
            text: The complete prompt to send.

        Returns:
            The agent's response text.

        Raises:
            asyncio.TimeoutError: If the agent doesn't respond in time.
            RuntimeError: If the agent process fails.
        """

    async def close(self) -> None:
        """Release any resources held by this agent.

        Default implementation does nothing. Override if your agent
        holds open connections or processes.
        """


# ── CLI Agent ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CliAgentConfig:
    """How to invoke a CLI agent.

    Attributes:
        name: Human-readable name (for logging and display).
        command: Executable name (must be on PATH).
        args: Arguments placed before the prompt.
        system_prompt: Context the bridge prepends to prompts.
        timeout: Max seconds to wait for a response.
        output_flag: For CLIs that write their final answer to a file
            (e.g. `codex exec -o FILE`): the flag that takes the path.
            The reply is read from that file, so progress logs on stdout
            never end up in a text message.
    """

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    system_prompt: str = ""
    timeout: float = DEFAULT_TIMEOUT
    output_flag: str | None = None
    # False for CLIs whose binary name is ambiguous (e.g. Cursor's `agent`):
    # they're only used when chosen explicitly with --agent.
    auto_detect: bool = True


class CliAgent(Agent):
    """Runs a CLI agent as a one-shot subprocess per message.

    Each call to ask() spawns a fresh process:
        {command} {args} "{prompt}"

    Stdout is captured as the response. Stderr is logged on failure.
    This is the simplest and most reliable approach — no process
    lifecycle management, no stdin/stdout protocol, no state leaks.

    The agent receives the complete prompt from the bridge. It does
    not manage system prompts or conversation context — that's the
    bridge's responsibility.

    Args:
        config: How to invoke the agent CLI.
    """

    def __init__(self, config: CliAgentConfig) -> None:
        self._config = config

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def system_prompt(self) -> str:
        return self._config.system_prompt

    async def ask(self, text: str) -> str:
        """Spawn the agent CLI with the prompt and return its output."""
        if self._config.output_flag is None:
            return await self._run([self._config.command, *self._config.args, text])

        with tempfile.TemporaryDirectory(prefix="aitextaroo-") as tmp:
            out_path = os.path.join(tmp, "reply.txt")
            cmd = [
                self._config.command,
                *self._config.args,
                self._config.output_flag,
                out_path,
                text,
            ]
            stdout = await self._run(cmd)
            try:
                with open(out_path, encoding="utf-8", errors="replace") as fh:
                    from_file = fh.read().strip()
            except OSError:
                from_file = ""
            return from_file or stdout

    async def _run(self, cmd: list[str]) -> str:
        """Run one agent process and return its stdout."""
        text = cmd[-1]
        logger.debug("Running: %s %s '%s...'", cmd[0], " ".join(cmd[1:-1]), text[:40])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=self._config.timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise

        if process.returncode != 0:
            error_text = stderr.decode(errors="replace")[:200]
            logger.warning(
                "Agent %s exited with code %d: %s",
                self._config.name, process.returncode, error_text,
            )

        return stdout.decode(errors="replace").strip()


# ── Agent Registry ───────────────────────────────────────────────

# Built-in agent configurations. Each entry defines how to invoke
# a known CLI agent. The bridge uses these to auto-detect and
# instantiate agents.
#
# To add a new agent: add an entry here and it works automatically.
# No other code changes needed.

# Shared by every agent. Texts can't prove who sent them, and some CLIs
# auto-approve their own tool calls in one-shot mode, so the prompt asks
# for a PIN (or an in-app confirmation) before anything irreversible.
SMS_SYSTEM_PROMPT = (
    "You are replying to SMS text messages from your user through AI Text-a-roo. "
    "Reply in plain text (no markdown), briefly: these are text messages with a "
    "1600 character limit. A text can't prove who sent it, so before anything "
    "sensitive or irreversible (spending money, messaging other people, deleting "
    "or changing things) ask the user to text their security PIN and check it with "
    "the aitextaroo verify_pin tool if you have it; otherwise ask them to confirm "
    "in your own app instead of acting on the text alone."
)

BUILTIN_AGENTS: dict[str, CliAgentConfig] = {
    "claude": CliAgentConfig(
        name="Claude Code",
        command="claude",
        args=["-p"],
        system_prompt=SMS_SYSTEM_PROMPT,
    ),
    "codex": CliAgentConfig(
        name="Codex",
        command="codex",
        # The bridge may run outside a git repo; colors would garble texts.
        args=["exec", "--skip-git-repo-check", "--color", "never"],
        output_flag="-o",
        system_prompt=SMS_SYSTEM_PROMPT,
    ),
    "hermes": CliAgentConfig(
        name="Hermes",
        command="hermes",
        # -z/--oneshot prints only the final reply (no banner or spinner).
        args=["-z"],
        system_prompt=SMS_SYSTEM_PROMPT,
    ),
    "openclaw": CliAgentConfig(
        name="OpenClaw",
        command="openclaw",
        # Prints only the final assistant text; diagnostics go to stderr.
        args=["agent", "exec"],
        system_prompt=SMS_SYSTEM_PROMPT,
    ),
    "grok": CliAgentConfig(
        name="Grok",
        command="grok",
        # -p/--single: one turn, response on stdout.
        args=["--no-auto-update", "-p"],
        system_prompt=SMS_SYSTEM_PROMPT,
    ),
    "gemini": CliAgentConfig(
        name="Gemini CLI",
        command="gemini",
        args=["-p"],
        system_prompt=SMS_SYSTEM_PROMPT,
    ),
    "antigravity": CliAgentConfig(
        name="Antigravity CLI",
        command="agy",
        # Headless: the response on stdout, notices on stderr.
        args=["-p"],
        system_prompt=SMS_SYSTEM_PROMPT,
    ),
    "goose": CliAgentConfig(
        name="Goose",
        command="goose",
        # -q prints only the model's response.
        args=["run", "-q", "--no-session", "-t"],
        system_prompt=SMS_SYSTEM_PROMPT,
    ),
    "cursor": CliAgentConfig(
        name="Cursor CLI",
        command="agent",
        args=["-p", "--trust"],
        system_prompt=SMS_SYSTEM_PROMPT,
        # Grok Build also installs a binary called `agent`.
        auto_detect=False,
    ),
}


def custom_agent(command_line: str, name: str = "Custom agent") -> CliAgent:
    """Build an agent from a full command line, e.g. "pnpm --silent --dir ~/nanoclaw run chat".

    The bridge appends the prompt as the last argument and reads stdout.
    """
    parts = shlex.split(command_line)
    if not parts:
        raise ValueError("Agent command is empty")
    command = os.path.expanduser(parts[0])
    args = [os.path.expanduser(p) for p in parts[1:]]
    config = CliAgentConfig(name=name, command=command, args=args, system_prompt=SMS_SYSTEM_PROMPT)
    return CliAgent(config)


def detect_agents() -> list[str]:
    """Find which supported agents are installed on this system.

    Returns:
        Agent names found on PATH, in preference order.
    """
    found = []
    for name, config in BUILTIN_AGENTS.items():
        if config.auto_detect and shutil.which(config.command):
            found.append(name)
            logger.debug("Detected agent: %s (%s)", config.name, config.command)
    return found


def create_agent(name: str) -> CliAgent:
    """Create an agent instance by name.

    Args:
        name: Key in BUILTIN_AGENTS (e.g., "claude", "hermes").

    Returns:
        A ready-to-use CliAgent.

    Raises:
        ValueError: If the agent name is not recognized.
    """
    config = BUILTIN_AGENTS.get(name)
    if config is None:
        available = ", ".join(BUILTIN_AGENTS.keys())
        raise ValueError(f"Unknown agent: {name!r}. Available: {available}")
    return CliAgent(config)
