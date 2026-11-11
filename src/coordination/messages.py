"""Message schema and counter tracking for negotiation overhead evaluation."""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class CoordinationMessage:
    msg_type: str  # 'negotiation_request', 'negotiation_response', 'negotiation_result'
    sender_id: str
    recipient_id: str
    payload: Dict[str, Any]


@dataclass
class MessageCounter:
    requests: int = 0
    responses: int = 0
    results: int = 0

    def log_message(self, msg_type: str):
        if msg_type == "negotiation_request":
            self.requests += 1
        elif msg_type == "negotiation_response":
            self.responses += 1
        elif msg_type == "negotiation_result":
            self.results += 1

    @property
    def total_messages(self) -> int:
        return self.requests + self.responses + self.results