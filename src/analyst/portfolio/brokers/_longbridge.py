from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass

import httpx

from analyst.env import get_env_value
from analyst.portfolio.types import PortfolioHolding

from ._base import BrokerAuthError, BrokerConnectionError, BrokerSyncResult

logger = logging.getLogger(__name__)

# Longbridge /v1/asset/stock returns only stocks; asset_class is always equity.
# Fund / bond endpoints can be added later.
_DEFAULT_ASSET_CLASS = "equity"

# Symbol format: "AAPL.US", "700.HK", "600519.SH"
# Convert to yfinance format: "AAPL", "0700.HK", "600519.SS"
_MARKET_SUFFIX_MAP: dict[str, str] = {
    "US": "",       # yfinance: no suffix for US
    "HK": ".HK",   # yfinance: .HK
    "SH": ".SS",   # yfinance uses .SS for Shanghai
    "SZ": ".SZ",   # yfinance: .SZ
    "SG": ".SI",   # yfinance: .SI for Singapore
    "JP": ".T",    # yfinance: .T for Tokyo
}


def _normalize_symbol(raw_symbol: str) -> str:
    """Convert Longbridge symbol format to yfinance-compatible ticker."""
    if "." not in raw_symbol:
        return raw_symbol.upper()

    parts = raw_symbol.rsplit(".", 1)
    ticker, market = parts[0], parts[1].upper()

    suffix = _MARKET_SUFFIX_MAP.get(market)
    if suffix is None:
        return raw_symbol.upper()

    if not suffix:
        # US market — no suffix
        return ticker.upper()

    # HK tickers are 4+ digits; pad if needed (e.g. "700" → "0700")
    if market == "HK" and ticker.isdigit():
        ticker = ticker.zfill(4)

    return f"{ticker}{suffix}".upper()


@dataclass(frozen=True)
class LongbridgeConfig:
    base_url: str
    app_key: str
    app_secret: str
    access_token: str
    timeout: float = 15.0

    @classmethod
    def from_env(
        cls,
        app_key: str = "",
        app_secret: str = "",
        access_token: str = "",
        base_url: str = "",
        **_kwargs: object,
    ) -> LongbridgeConfig:
        return cls(
            base_url=base_url or get_env_value("ANALYST_LONGBRIDGE_BASE_URL", default="https://openapi.longportapp.com"),
            app_key=app_key or get_env_value("ANALYST_LONGBRIDGE_APP_KEY"),
            app_secret=app_secret or get_env_value("ANALYST_LONGBRIDGE_APP_SECRET"),
            access_token=access_token or get_env_value("ANALYST_LONGBRIDGE_ACCESS_TOKEN"),
        )

    def validate(self) -> None:
        missing = []
        if not self.app_key:
            missing.append("ANALYST_LONGBRIDGE_APP_KEY")
        if not self.app_secret:
            missing.append("ANALYST_LONGBRIDGE_APP_SECRET")
        if not self.access_token:
            missing.append("ANALYST_LONGBRIDGE_ACCESS_TOKEN")
        if missing:
            raise BrokerAuthError(
                f"Longbridge credentials not configured. Set env vars: {', '.join(missing)}"
            )


class LongbridgeAdapter:
    broker_name: str = "longbridge"

    def __init__(self, config: LongbridgeConfig | None = None) -> None:
        self.config = config or LongbridgeConfig.from_env()
        self._client = httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )

    def _sign_headers(self, method: str, path: str, params: str = "", body: str = "") -> dict[str, str]:
        """Compute Longbridge HMAC-SHA256 request signature."""
        timestamp = str(int(time.time()))
        payload_hash = hashlib.sha1(body.encode()).hexdigest()

        canonical = (
            f"{method}|{path}|{params}|"
            f"authorization:{self.config.access_token}\n"
            f"x-api-key:{self.config.app_key}\n"
            f"x-timestamp:{timestamp}\n"
            f"|authorization;x-api-key;x-timestamp|{payload_hash}"
        )

        canonical_hash = hashlib.sha1(canonical.encode()).hexdigest()
        sign_str = f"HMAC-SHA256|{canonical_hash}"

        signature = hmac.new(
            self.config.app_secret.encode(),
            sign_str.encode(),
            hashlib.sha256,
        ).hexdigest()

        return {
            "X-Api-Key": self.config.app_key,
            "Authorization": self.config.access_token,
            "X-Timestamp": timestamp,
            "X-Api-Signature": (
                f"HMAC-SHA256 SignedHeaders=authorization;x-api-key;x-timestamp, "
                f"Signature={signature}"
            ),
            "Content-Type": "application/json; charset=utf-8",
        }

    def _request(self, method: str, path: str, params: str = "") -> dict:
        headers = self._sign_headers(method, path, params=params)
        url = f"{path}?{params}" if params else path
        try:
            resp = self._client.request(method, url, headers=headers)
        except httpx.ConnectError as exc:
            raise BrokerConnectionError(
                f"Cannot reach Longbridge API at {self.config.base_url}: {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise BrokerConnectionError(f"Longbridge API error: {exc}") from exc

        data = resp.json()
        code = data.get("code", -1)
        if code in (401001, 401002):
            raise BrokerAuthError(
                "Longbridge access token is expired or invalid. "
                "Refresh your token at https://open.longportapp.com"
            )
        if resp.status_code == 401:
            raise BrokerAuthError("Longbridge authentication failed.")
        if code != 0:
            raise BrokerConnectionError(
                f"Longbridge API error (code={code}): {data.get('message', 'unknown')}"
            )
        return data

    def validate_session(self) -> bool:
        self.config.validate()
        self._request("GET", "/v1/asset/account")
        return True

    def list_accounts(self) -> list[str]:
        self.config.validate()
        data = self._request("GET", "/v1/asset/account")
        accounts = data.get("data", {})
        # Longbridge typically has a single account; return account_channel as ID
        channels = []
        if isinstance(accounts, dict):
            for item in accounts.get("list", [accounts]):
                channel = item.get("account_channel", "")
                if channel:
                    channels.append(channel)
        return channels or ["default"]

    def fetch_positions(self, account_id: str = "") -> BrokerSyncResult:
        self.config.validate()
        data = self._request("GET", "/v1/asset/stock")

        all_stocks: list[dict] = []
        for channel_group in data.get("data", {}).get("list", []):
            all_stocks.extend(channel_group.get("stock_info", []))

        skipped: list[str] = []
        warnings: list[str] = []
        currencies: set[str] = set()
        has_market_value = False

        # Single pass: collect parsed positions, then compute weights
        parsed: list[tuple[str, str, str, float]] = []  # (symbol, name, currency, notional)
        for stock in all_stocks:
            quantity = float(stock.get("quantity", 0))
            raw_symbol = stock.get("symbol", "UNKNOWN")

            if quantity == 0:
                skipped.append(f"{raw_symbol}: zero position")
                continue

            # Prefer market_value if the API provides it; fall back to cost basis
            market_value = stock.get("market_value") or stock.get("market_val")
            if market_value is not None:
                notional = abs(float(market_value))
                has_market_value = True
            else:
                cost_price = float(stock.get("cost_price", 0))
                notional = abs(cost_price * quantity)

            currency = stock.get("currency", "")
            if currency:
                currencies.add(currency)

            parsed.append((
                _normalize_symbol(raw_symbol),
                stock.get("symbol_name", raw_symbol),
                currency,
                notional,
            ))

        total_notional = sum(n for _, _, _, n in parsed)

        holdings: list[PortfolioHolding] = []
        for symbol, name, _currency, notional in parsed:
            weight = notional / total_notional if total_notional > 0 else 0.0
            holdings.append(PortfolioHolding(
                symbol=symbol,
                name=name,
                asset_class=_DEFAULT_ASSET_CLASS,
                weight=weight,
                notional=notional,
            ))

        if not has_market_value and holdings:
            warnings.append(
                "Weights are based on cost basis (cost_price * quantity), not live market value. "
                "Run portfolio-risk to get accurate weights from live prices."
            )
        if len(currencies) > 1:
            warnings.append(f"Mixed currencies detected ({', '.join(sorted(currencies))})")

        resolved_account = account_id or "default"

        return BrokerSyncResult(
            broker="longbridge",
            account_id=resolved_account,
            holdings=holdings,
            raw_position_count=len(all_stocks),
            skipped=skipped,
            warnings=warnings,
        )
