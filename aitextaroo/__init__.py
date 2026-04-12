"""AI Text-a-roo — give any AI agent a phone number.

Connect to the AI Text-a-roo SMS gateway to receive and send
text messages through any AI agent framework.

Example:
    >>> from aitextaroo import TextarooClient
    >>> client = TextarooClient(api_key="your-key")
    >>> async for message in client.listen():
    ...     print(f"Got: {message.text}")
    ...     await client.send(f"You said: {message.text}")
"""

from aitextaroo.client import TextarooClient
from aitextaroo.models import InboundMessage, StreamEvent

__version__ = "0.1.2"
__all__ = ["TextarooClient", "InboundMessage", "StreamEvent"]
