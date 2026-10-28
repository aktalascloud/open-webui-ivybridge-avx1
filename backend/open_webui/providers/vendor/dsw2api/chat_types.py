"""Protocol-independent execution events and results."""
from dataclasses import dataclass, field


@dataclass
class ChatEvent:
    kind: str
    text: str = ''
    call: dict | None = None
    calls: list[dict] | None = None


@dataclass
class ChatResult:
    text: str = ''
    reasoning: str = ''
    calls: list[dict] = field(default_factory=list)
