from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from analyst.contracts import Serializable
from analyst.portfolio.types import PortfolioHolding


class BrokerError(Exception):
    """Base exception for broker adapter errors."""


class BrokerAuthError(BrokerError):
    """Raised when the broker session is expired or invalid."""


class BrokerConnectionError(BrokerError):
    """Raised when the broker gateway is unreachable."""


@dataclass(frozen=True)
class BrokerSyncResult(Serializable):
    broker: str
    account_id: str
    holdings: list[PortfolioHolding]
    raw_position_count: int
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class BrokerAdapter(Protocol):
    broker_name: str

    def validate_session(self) -> bool: ...

    def list_accounts(self) -> list[str]: ...

    def fetch_positions(self, account_id: str = "") -> BrokerSyncResult: ...
