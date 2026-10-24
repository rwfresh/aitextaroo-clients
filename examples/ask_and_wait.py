"""Human in the loop by SMS: text a question, then wait for the answer.

Usage:
    AITEXTAROO_API_KEY=your-key python examples/ask_and_wait.py
    (or run `aitextaroo-setup --save` once and drop the env var)
"""

import asyncio

from aitextaroo import TextarooClient
from aitextaroo.credentials import load_api_key


async def main() -> None:
    api_key = load_api_key()
    if not api_key:
        print("Set AITEXTAROO_API_KEY or run `aitextaroo-setup --phone +1... --save`")
        return

    client = TextarooClient(api_key=api_key)
    try:
        await client.send("All 318 tests pass. Open a PR? Reply YES or NO.")

        # Each wait lasts up to 120 seconds; keep asking for a few minutes.
        for _ in range(3):
            reply = await client.wait_for_reply(timeout_seconds=90)
            if reply is None:
                continue
            if reply.text.strip().lower().startswith("y"):
                await client.send("On it. I'll text you the PR link.")
            else:
                await client.send("OK, holding off.")
            return

        print("No reply yet; carry on without it.")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
