from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from analyst.env import get_env_value
from analyst.portfolio.types import PortfolioHolding

from ._base import BrokerAuthError, BrokerConnectionError, BrokerError, BrokerSyncResult

logger = logging.getLogger(__name__)

_SEC_TYPE_MAP: dict[str, str] = {
    "STK": "equity",
    "OPT": "option",
    "FUT": "futures",
    "WAR": "warrant",
    "FUND": "fund",
    "BOND": "fixed_income",
    "CASH": "fx",
}


def _load_private_key(key_or_path: str) -> object:
    """Load an RSA private key from PEM content or a file path.

    Returns a cryptography private key object.
    Raises BrokerError if the cryptography package is not installed.
    """
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except ImportError:
        raise BrokerError(
            "Tiger adapter requires the 'cryptography' package for RSA signing. "
            "Install it with: pip install cryptography"
        ) from None

    if key_or_path.strip().startswith("-----BEGIN"):
        pem_bytes = key_or_path.encode()
    else:
        pem_path = Path(key_or_path).expanduser()
        if not pem_path.exists():
            raise BrokerAuthError(f"Tiger private key file not found: {pem_path}")
        pem_bytes = pem_path.read_bytes()

    try:
        return load_pem_private_key(pem_bytes, password=None)
    except Exception as exc:
        raise BrokerAuthError(f"Failed to load Tiger private key: {exc}") from exc


def _rsa_sign(private_key: object, content: str) -> str:
    """RSA-SHA256 sign content and return base64-encoded signature."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    signature = private_key.sign(  # type: ignore[union-attr]
        content.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


@dataclass(frozen=True)
class TigerConfig:
    gateway_url: str
    tiger_id: str
    private_key: str  # PEM content or file path
    account: str = ""
    timeout: float = 15.0

    @classmethod
    def from_env(
        cls,
        tiger_id: str = "",
        private_key: str = "",
        account: str = "",
        gateway_url: str = "",
        **_kwargs: object,
    ) -> TigerConfig:
        return cls(
            gateway_url=gateway_url or get_env_value("ANALYST_TIGER_GATEWAY_URL", default="https://openapi.itigerup.com/gateway"),
            tiger_id=tiger_id or get_env_value("ANALYST_TIGER_ID"),
            private_key=private_key or get_env_value("ANALYST_TIGER_PRIVATE_KEY"),
            account=account or get_env_value("ANALYST_TIGER_ACCOUNT"),
        )

    def validate(self) -> None:
        missing = []
        if not self.tiger_id:
            missing.append("ANALYST_TIGER_ID")
        if not self.private_key:
            missing.append("ANALYST_TIGER_PRIVATE_KEY")
        if missing:
            raise BrokerAuthError(
                f"Tiger credentials not configured. Set env vars: {', '.join(missing)}"
            )


class TigerAdapter:
    broker_name: str = "tiger"

    def __init__(self, config: TigerConfig | None = None) -> None:
        self.config = config or TigerConfig.from_env()
        self._client = httpx.Client(timeout=self.config.timeout)
        self._private_key: object | None = None

    def _get_private_key(self) -> object:
        if self._private_key is None:
            self._private_key = _load_private_key(self.config.private_key)
        return self._private_key

    def _build_request(self, method: str, biz_content: dict | None = None) -> dict:
        """Build a signed Tiger API gateway request."""
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        params = {
            "tiger_id": self.config.tiger_id,
            "method": method,
            "charset": "UTF-8",
            "sign_type": "RSA",
            "timestamp": timestamp,
            "version": "3.0",
        }
        if biz_content is not None:
            params["biz_content"] = json.dumps(biz_content, separators=(",", ":"))

        # Sign: sort params alphabetically, join as k=v&k=v, RSA-SHA256 sign
        sign_content = "&".join(
            f"{k}={params[k]}" for k in sorted(params)
        )
        private_key = self._get_private_key()
        params["sign"] = _rsa_sign(private_key, sign_content)
        return params

    def _call(self, method: str, biz_content: dict | None = None) -> dict:
        payload = self._build_request(method, biz_content)
        try:
            resp = self._client.post(self.config.gateway_url, json=payload)
        except httpx.ConnectError as exc:
            raise BrokerConnectionError(
                f"Cannot reach Tiger API at {self.config.gateway_url}: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise BrokerConnectionError(f"Tiger API error: {exc}") from exc

        data = resp.json()
        code = data.get("code", -1)
        if code in (40001, 40002, 40003):
            raise BrokerAuthError(
                "Tiger authentication failed. Check your tiger_id and private key."
            )
        if code != 0:
            raise BrokerConnectionError(
                f"Tiger API error (code={code}): {data.get('message', 'unknown')}"
            )
        return data

    def validate_session(self) -> bool:
        self.config.validate()
        self._call("assets", {"account": self.config.account} if self.config.account else None)
        return True

    def list_accounts(self) -> list[str]:
        self.config.validate()
        if self.config.account:
            return [self.config.account]
        # Tiger typically uses a single account bound to the API key
        data = self._call("assets")
        items = data.get("data", {}).get("items", [])
        accounts = list({item.get("account", "") for item in items if item.get("account")})
        return accounts or ["default"]

    def fetch_positions(self, account_id: str = "") -> BrokerSyncResult:
        self.config.validate()
        resolved = account_id or self.config.account

        biz_content: dict = {}
        if resolved:
            biz_content["account"] = resolved

        data = self._call("positions", biz_content or None)

        positions = data.get("data", {}).get("items", [])
        # Also handle flat list response
        if isinstance(data.get("data"), list):
            positions = data["data"]

        holdings: list[PortfolioHolding] = []
        skipped: list[str] = []
        warnings: list[str] = []
        currencies: set[str] = set()

        total_abs_mkt_value = sum(
            abs(float(p.get("market_value", 0)))
            for p in positions
        )

        for pos in positions:
            contract = pos.get("contract", {})
            symbol = contract.get("symbol", pos.get("symbol", "UNKNOWN"))
            sec_type = contract.get("sec_type", pos.get("sec_type", "STK"))
            currency = contract.get("currency", pos.get("currency", "USD"))

            quantity = float(pos.get("quantity", 0))
            market_value = float(pos.get("market_value", 0))

            if quantity == 0 and market_value == 0:
                skipped.append(f"{symbol}: zero position")
                continue

            currencies.add(currency)

            asset_class = _SEC_TYPE_MAP.get(sec_type, sec_type.lower())
            notional = abs(market_value)
            weight = notional / total_abs_mkt_value if total_abs_mkt_value > 0 else 0.0

            # Build display name from contract info
            name = contract.get("name", "") or pos.get("name", symbol)

            holdings.append(PortfolioHolding(
                symbol=symbol.upper(),
                name=name,
                asset_class=asset_class,
                weight=weight,
                notional=notional,
            ))

        if len(currencies) > 1:
            warnings.append(f"Mixed currencies detected ({', '.join(sorted(currencies))})")

        return BrokerSyncResult(
            broker="tiger",
            account_id=resolved or "default",
            holdings=holdings,
            raw_position_count=len(positions),
            skipped=skipped,
            warnings=warnings,
        )
