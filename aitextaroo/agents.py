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
import shutil
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
    """

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    system_prompt: str = ""
    timeout: float = DEFAULT_TIMEOUT


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
        cmd = [self._config.command, *self._config.args, text]

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

BUILTIN_AGENTS: dict[str, CliAgentConfig] = {
    "claude": CliAgentConfig(
        name="Claude Code",
        command="claude",
        args=["-p"],
        system_prompt=(
            "You are receiving SMS text messages from a user. "
            "Respond concisely — these are text messages with a 1600 character limit."
        ),
    ),
    "hermes": CliAgentConfig(
        name="Hermes",
        command="hermes",
        args=["--pipe"],
        system_prompt=(
            "You are receiving SMS text messages from a user via AI Text-a-roo. "
            "Respond conversationally. Keep responses concise — they're text messages."
        ),
    ),
    "openclaw": CliAgentConfig(
        name="OpenClaw",
        command="openclaw",
        args=["--pipe"],
        system_prompt="You are receiving SMS text messages. Respond concisely.",
    ),
    "nanoclaw": CliAgentConfig(
        name="NanoClaw",
        command="nanoclaw",
        args=["--pipe"],
        system_prompt="You are receiving SMS text messages. Respond concisely.",
    ),
}


def detect_agents() -> list[str]:
    """Find which supported agents are installed on this system.

    Returns:
        Agent names found on PATH, in preference order.
    """
    found = []
    for name, config in BUILTIN_AGENTS.items():
        if shutil.which(config.command):
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
