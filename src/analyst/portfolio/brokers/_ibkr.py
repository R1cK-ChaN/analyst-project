from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from analyst.env import get_env_value
from analyst.portfolio.types import PortfolioHolding

from ._base import BrokerAuthError, BrokerConnectionError, BrokerSyncResult

logger = logging.getLogger(__name__)

_ASSET_CLASS_MAP: dict[str, str] = {
    "STK": "equity",
    "OPT": "option",
    "FUT": "futures",
    "CASH": "fx",
    "BOND": "fixed_income",
}


@dataclass(frozen=True)
class IBKRConfig:
    gateway_url: str
    account_id: str = ""
    verify_ssl: bool = False
    timeout: float = 15.0

    @classmethod
    def from_env(
        cls,
        gateway_url: str = "",
        account_id: str = "",
        **_kwargs: object,
    ) -> IBKRConfig:
        return cls(
            gateway_url=gateway_url or get_env_value("ANALYST_IBKR_GATEWAY_URL", default="https://localhost:5000/v1/api"),
            account_id=account_id or get_env_value("ANALYST_IBKR_ACCOUNT_ID", default=""),
        )


class IBKRClientPortalAdapter:
    broker_name: str = "ibkr"

    def __init__(self, config: IBKRConfig | None = None) -> None:
        self.config = config or IBKRConfig.from_env()
        self._client = httpx.Client(
            base_url=self.config.gateway_url,
            verify=self.config.verify_ssl,
            timeout=self.config.timeout,
        )

    def validate_session(self) -> bool:
        try:
            resp = self._client.post("/sso/validate")
        except httpx.ConnectError as exc:
            raise BrokerConnectionError(
                f"Cannot reach IBKR Gateway at {self.config.gateway_url}. "
                "Make sure the Client Portal Gateway is running."
            ) from exc
        except httpx.HTTPError as exc:
            raise BrokerConnectionError(f"IBKR Gateway error: {exc}") from exc

        if resp.status_code == 401 or not resp.json().get("authenticated", False):
            raise BrokerAuthError(
                "IBKR session is not authenticated. "
                "Open the Client Portal Gateway in your browser and log in."
            )
        return True

    def list_accounts(self) -> list[str]:
        self.validate_session()
        try:
            resp = self._client.get("/portfolio/accounts")
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise BrokerConnectionError(f"Cannot reach IBKR Gateway: {exc}") from exc
        except httpx.HTTPError as exc:
            raise BrokerConnectionError(f"IBKR Gateway error: {exc}") from exc

        accounts = resp.json()
        return [acct["accountId"] for acct in accounts if "accountId" in acct]

    def fetch_positions(self, account_id: str = "") -> BrokerSyncResult:
        resolved = self._resolve_account(account_id)
        try:
            resp = self._client.get(f"/portfolio/{resolved}/positions/0")
            resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise BrokerConnectionError(f"Cannot reach IBKR Gateway: {exc}") from exc
        except httpx.HTTPError as exc:
            raise BrokerConnectionError(f"IBKR Gateway error: {exc}") from exc

        positions = resp.json()
        holdings: list[PortfolioHolding] = []
        skipped: list[str] = []
        warnings: list[str] = []
        currencies: set[str] = set()

        total_abs_mkt_value = sum(abs(p.get("mktValue", 0)) for p in positions)

        for pos in positions:
            mkt_value = pos.get("mktValue", 0)
            position_qty = pos.get("position", 0)
            contract_desc = pos.get("contractDesc", "")
            ticker = pos.get("ticker", "")
            symbol = ticker or (contract_desc.split()[0] if contract_desc else "UNKNOWN")

            if position_qty == 0 and mkt_value == 0:
                skipped.append(f"{symbol}: zero position")
                continue

            currency = pos.get("currency", "USD")
            currencies.add(currency)

            asset_class_raw = pos.get("assetClass", "")
            asset_class = _ASSET_CLASS_MAP.get(asset_class_raw, asset_class_raw.lower())

            notional = abs(mkt_value)
            weight = notional / total_abs_mkt_value if total_abs_mkt_value > 0 else 0.0

            holdings.append(PortfolioHolding(
                symbol=symbol.upper(),
                name=contract_desc,
                asset_class=asset_class,
                weight=weight,
                notional=notional,
            ))

        if len(currencies) > 1:
            warnings.append(f"Mixed currencies detected ({', '.join(sorted(currencies))})")

        return BrokerSyncResult(
            broker="ibkr",
            account_id=resolved,
            holdings=holdings,
            raw_position_count=len(positions),
            skipped=skipped,
            warnings=warnings,
        )

    def _resolve_account(self, account_id: str) -> str:
        if account_id:
            return account_id
        if self.config.account_id:
            return self.config.account_id
        accounts = self.list_accounts()
        if not accounts:
            raise BrokerConnectionError("No accounts found in IBKR Gateway.")
        if len(accounts) > 1:
            logger.warning(
                "Multiple IBKR accounts found (%s), using first: %s",
                ", ".join(accounts),
                accounts[0],
            )
        return accounts[0]
