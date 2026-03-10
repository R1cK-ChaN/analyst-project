from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from analyst.portfolio.brokers import (
    BrokerAuthError,
    BrokerConnectionError,
    BrokerError,
    IBKRClientPortalAdapter,
    IBKRConfig,
    LongbridgeAdapter,
    LongbridgeConfig,
    TigerAdapter,
    TigerConfig,
    create_broker_adapter,
)
from analyst.portfolio.brokers._ibkr import _ASSET_CLASS_MAP
from analyst.portfolio.brokers._longbridge import _normalize_symbol
from analyst.portfolio.brokers._tiger import _SEC_TYPE_MAP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data: object, status_code: int = 200) -> httpx.Response:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp,
        )
    return resp


def _make_adapter() -> IBKRClientPortalAdapter:
    config = IBKRConfig(gateway_url="https://localhost:5000/v1/api", account_id="U1234567")
    return IBKRClientPortalAdapter(config)


def _sample_position(
    ticker: str = "AAPL",
    contract_desc: str = "APPLE INC",
    asset_class: str = "STK",
    mkt_value: float = 50000.0,
    position: float = 100,
    currency: str = "USD",
    **overrides: object,
) -> dict:
    pos = {
        "ticker": ticker,
        "contractDesc": contract_desc,
        "assetClass": asset_class,
        "mktValue": mkt_value,
        "position": position,
        "currency": currency,
    }
    pos.update(overrides)
    return pos


# ---------------------------------------------------------------------------
# TestIBKRAssetClassMapping
# ---------------------------------------------------------------------------

class TestIBKRAssetClassMapping:
    def test_stk_maps_to_equity(self):
        assert _ASSET_CLASS_MAP["STK"] == "equity"

    def test_opt_maps_to_option(self):
        assert _ASSET_CLASS_MAP["OPT"] == "option"

    def test_fut_maps_to_futures(self):
        assert _ASSET_CLASS_MAP["FUT"] == "futures"

    def test_cash_maps_to_fx(self):
        assert _ASSET_CLASS_MAP["CASH"] == "fx"

    def test_bond_maps_to_fixed_income(self):
        assert _ASSET_CLASS_MAP["BOND"] == "fixed_income"

    def test_unknown_passthrough(self):
        adapter = _make_adapter()
        positions = [_sample_position(asset_class="CRYPTO", mkt_value=10000)]
        with patch.object(adapter._client, "get", return_value=_mock_response(positions)):
            result = adapter.fetch_positions()
        assert result.holdings[0].asset_class == "crypto"


# ---------------------------------------------------------------------------
# TestIBKRPositionMapping
# ---------------------------------------------------------------------------

class TestIBKRPositionMapping:
    def test_single_position(self):
        adapter = _make_adapter()
        positions = [_sample_position(ticker="MSFT", contract_desc="MICROSOFT CORP", mkt_value=100000)]
        with patch.object(adapter._client, "get", return_value=_mock_response(positions)):
            result = adapter.fetch_positions()

        assert len(result.holdings) == 1
        h = result.holdings[0]
        assert h.symbol == "MSFT"
        assert h.name == "MICROSOFT CORP"
        assert h.asset_class == "equity"
        assert h.notional == 100000.0
        assert h.weight == pytest.approx(1.0)
        assert result.raw_position_count == 1
        assert result.broker == "ibkr"
        assert result.account_id == "U1234567"

    def test_empty_positions(self):
        adapter = _make_adapter()
        with patch.object(adapter._client, "get", return_value=_mock_response([])):
            result = adapter.fetch_positions()

        assert result.holdings == []
        assert result.raw_position_count == 0

    def test_mixed_currencies_warning(self):
        adapter = _make_adapter()
        positions = [
            _sample_position(ticker="AAPL", mkt_value=50000, currency="USD"),
            _sample_position(ticker="BMW", mkt_value=30000, currency="EUR"),
        ]
        with patch.object(adapter._client, "get", return_value=_mock_response(positions)):
            result = adapter.fetch_positions()

        assert len(result.warnings) == 1
        assert "Mixed currencies" in result.warnings[0]
        assert "EUR" in result.warnings[0]
        assert "USD" in result.warnings[0]

    def test_zero_position_skipped(self):
        adapter = _make_adapter()
        positions = [
            _sample_position(ticker="AAPL", mkt_value=50000, position=100),
            _sample_position(ticker="GOOG", mkt_value=0, position=0),
        ]
        with patch.object(adapter._client, "get", return_value=_mock_response(positions)):
            result = adapter.fetch_positions()

        assert len(result.holdings) == 1
        assert result.holdings[0].symbol == "AAPL"
        assert len(result.skipped) == 1
        assert "GOOG" in result.skipped[0]

    def test_short_positions_use_abs(self):
        adapter = _make_adapter()
        positions = [
            _sample_position(ticker="AAPL", mkt_value=50000, position=100),
            _sample_position(ticker="TSLA", mkt_value=-30000, position=-50),
        ]
        with patch.object(adapter._client, "get", return_value=_mock_response(positions)):
            result = adapter.fetch_positions()

        assert len(result.holdings) == 2
        tsla = next(h for h in result.holdings if h.symbol == "TSLA")
        assert tsla.notional == 30000.0
        assert tsla.weight > 0

    def test_weights_sum_to_one(self):
        adapter = _make_adapter()
        positions = [
            _sample_position(ticker="AAPL", mkt_value=50000),
            _sample_position(ticker="MSFT", mkt_value=30000),
            _sample_position(ticker="GOOG", mkt_value=20000),
        ]
        with patch.object(adapter._client, "get", return_value=_mock_response(positions)):
            result = adapter.fetch_positions()

        total_weight = sum(h.weight for h in result.holdings)
        assert total_weight == pytest.approx(1.0)

    def test_symbol_fallback_to_contract_desc(self):
        adapter = _make_adapter()
        positions = [_sample_position(ticker="", contract_desc="SPY 240119P450", mkt_value=10000)]
        with patch.object(adapter._client, "get", return_value=_mock_response(positions)):
            result = adapter.fetch_positions()

        assert result.holdings[0].symbol == "SPY"


# ---------------------------------------------------------------------------
# TestIBKRSessionValidation
# ---------------------------------------------------------------------------

class TestIBKRSessionValidation:
    def test_valid_session(self):
        adapter = _make_adapter()
        with patch.object(adapter._client, "post", return_value=_mock_response({"authenticated": True})):
            assert adapter.validate_session() is True

    def test_expired_session_raises_auth_error(self):
        adapter = _make_adapter()
        with patch.object(adapter._client, "post", return_value=_mock_response({"authenticated": False})):
            with pytest.raises(BrokerAuthError, match="not authenticated"):
                adapter.validate_session()

    def test_401_raises_auth_error(self):
        adapter = _make_adapter()
        resp = _mock_response({"authenticated": False}, status_code=401)
        resp.raise_for_status.side_effect = None  # 401 handled by our code, not raise_for_status
        with patch.object(adapter._client, "post", return_value=resp):
            with pytest.raises(BrokerAuthError):
                adapter.validate_session()

    def test_unreachable_raises_connection_error(self):
        adapter = _make_adapter()
        with patch.object(adapter._client, "post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(BrokerConnectionError, match="Cannot reach"):
                adapter.validate_session()


# ---------------------------------------------------------------------------
# TestBrokerFactory
# ---------------------------------------------------------------------------

# ===========================================================================
# Longbridge Tests
# ===========================================================================


def _make_longbridge_adapter() -> LongbridgeAdapter:
    config = LongbridgeConfig(
        base_url="https://openapi.longportapp.com",
        app_key="test_key",
        app_secret="test_secret",
        access_token="test_token",
    )
    return LongbridgeAdapter(config)


def _lb_api_response(stock_info: list[dict], code: int = 0) -> dict:
    return {
        "code": code,
        "data": {"list": [{"account_channel": "lb", "stock_info": stock_info}]},
    }


def _lb_stock(
    symbol: str = "AAPL.US",
    symbol_name: str = "Apple Inc",
    quantity: str = "100",
    cost_price: str = "150.00",
    currency: str = "USD",
    market: str = "US",
    **overrides: object,
) -> dict:
    s = {
        "symbol": symbol,
        "symbol_name": symbol_name,
        "quantity": quantity,
        "cost_price": cost_price,
        "currency": currency,
        "market": market,
    }
    s.update(overrides)
    return s


class TestLongbridgeSymbolNormalization:
    def test_us_strip_suffix(self):
        assert _normalize_symbol("AAPL.US") == "AAPL"

    def test_hk_pad_to_four_digits(self):
        assert _normalize_symbol("700.HK") == "0700.HK"

    def test_hk_already_four_digits(self):
        assert _normalize_symbol("9988.HK") == "9988.HK"

    def test_shanghai_suffix(self):
        assert _normalize_symbol("600519.SH") == "600519.SS"

    def test_shenzhen_kept(self):
        assert _normalize_symbol("000001.SZ") == "000001.SZ"

    def test_no_dot_passthrough(self):
        assert _normalize_symbol("TSLA") == "TSLA"

    def test_unknown_market_passthrough(self):
        assert _normalize_symbol("XYZ.XX") == "XYZ.XX"


class TestLongbridgePositionMapping:
    def test_single_position(self):
        adapter = _make_longbridge_adapter()
        api_data = _lb_api_response([_lb_stock()])
        with patch.object(adapter._client, "request", return_value=_mock_response(api_data)):
            result = adapter.fetch_positions()

        assert len(result.holdings) == 1
        h = result.holdings[0]
        assert h.symbol == "AAPL"
        assert h.name == "Apple Inc"
        assert h.asset_class == "equity"
        assert h.notional == 15000.0  # 100 * 150.00
        assert h.weight == pytest.approx(1.0)
        assert result.broker == "longbridge"

    def test_empty_positions(self):
        adapter = _make_longbridge_adapter()
        api_data = _lb_api_response([])
        with patch.object(adapter._client, "request", return_value=_mock_response(api_data)):
            result = adapter.fetch_positions()

        assert result.holdings == []

    def test_zero_quantity_skipped(self):
        adapter = _make_longbridge_adapter()
        api_data = _lb_api_response([
            _lb_stock(symbol="AAPL.US", quantity="100", cost_price="150"),
            _lb_stock(symbol="GOOG.US", quantity="0", cost_price="100"),
        ])
        with patch.object(adapter._client, "request", return_value=_mock_response(api_data)):
            result = adapter.fetch_positions()

        assert len(result.holdings) == 1
        assert result.holdings[0].symbol == "AAPL"
        assert len(result.skipped) == 1
        assert "GOOG" in result.skipped[0]

    def test_mixed_currencies_warning(self):
        adapter = _make_longbridge_adapter()
        api_data = _lb_api_response([
            _lb_stock(symbol="AAPL.US", currency="USD", quantity="100", cost_price="150"),
            _lb_stock(symbol="700.HK", currency="HKD", quantity="200", cost_price="380"),
        ])
        with patch.object(adapter._client, "request", return_value=_mock_response(api_data)):
            result = adapter.fetch_positions()

        assert any("Mixed currencies" in w for w in result.warnings)

    def test_cost_basis_warning_when_no_market_value(self):
        adapter = _make_longbridge_adapter()
        api_data = _lb_api_response([_lb_stock()])
        with patch.object(adapter._client, "request", return_value=_mock_response(api_data)):
            result = adapter.fetch_positions()

        assert any("cost basis" in w for w in result.warnings)

    def test_market_value_preferred_over_cost(self):
        adapter = _make_longbridge_adapter()
        stock = _lb_stock(quantity="100", cost_price="150.00", market_value="17500.00")
        api_data = _lb_api_response([stock])
        with patch.object(adapter._client, "request", return_value=_mock_response(api_data)):
            result = adapter.fetch_positions()

        assert result.holdings[0].notional == 17500.0
        assert not any("cost basis" in w for w in result.warnings)

    def test_weights_sum_to_one(self):
        adapter = _make_longbridge_adapter()
        api_data = _lb_api_response([
            _lb_stock(symbol="AAPL.US", quantity="100", cost_price="150"),
            _lb_stock(symbol="MSFT.US", quantity="50", cost_price="300"),
            _lb_stock(symbol="700.HK", quantity="200", cost_price="380"),
        ])
        with patch.object(adapter._client, "request", return_value=_mock_response(api_data)):
            result = adapter.fetch_positions()

        total = sum(h.weight for h in result.holdings)
        assert total == pytest.approx(1.0)


class TestLongbridgeSessionValidation:
    def test_valid_session(self):
        adapter = _make_longbridge_adapter()
        api_data = {"code": 0, "data": {}}
        with patch.object(adapter._client, "request", return_value=_mock_response(api_data)):
            assert adapter.validate_session() is True

    def test_expired_token_raises_auth_error(self):
        adapter = _make_longbridge_adapter()
        api_data = {"code": 401001, "message": "token expired"}
        with patch.object(adapter._client, "request", return_value=_mock_response(api_data)):
            with pytest.raises(BrokerAuthError, match="expired"):
                adapter.validate_session()

    def test_missing_credentials_raises_auth_error(self):
        config = LongbridgeConfig(
            base_url="https://openapi.longportapp.com",
            app_key="",
            app_secret="",
            access_token="",
        )
        adapter = LongbridgeAdapter(config)
        with pytest.raises(BrokerAuthError, match="not configured"):
            adapter.validate_session()

    def test_unreachable_raises_connection_error(self):
        adapter = _make_longbridge_adapter()
        with patch.object(adapter._client, "request", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(BrokerConnectionError, match="Cannot reach"):
                adapter.validate_session()


# ===========================================================================
# Tiger Tests
# ===========================================================================


def _make_tiger_adapter() -> TigerAdapter:
    config = TigerConfig(
        gateway_url="https://openapi.itigerup.com/gateway",
        tiger_id="test_id",
        private_key="test_key",
        account="DU123456",
    )
    adapter = TigerAdapter(config)
    return adapter


def _tiger_api_response(items: list[dict], code: int = 0) -> dict:
    return {
        "code": code,
        "message": "success",
        "data": {"items": items},
    }


def _tiger_position(
    symbol: str = "AAPL",
    sec_type: str = "STK",
    currency: str = "USD",
    quantity: float = 100,
    market_value: float = 17500.0,
    name: str = "Apple Inc",
    **overrides: object,
) -> dict:
    pos = {
        "contract": {
            "symbol": symbol,
            "sec_type": sec_type,
            "currency": currency,
            "name": name,
        },
        "quantity": quantity,
        "market_value": market_value,
        "average_cost": 150.0,
    }
    pos.update(overrides)
    return pos


# Patch RSA signing for all Tiger tests since cryptography may not be installed
_MOCK_SIGN_PATCH = patch(
    "analyst.portfolio.brokers._tiger._rsa_sign",
    return_value="mock_signature",
)
_MOCK_LOAD_KEY_PATCH = patch(
    "analyst.portfolio.brokers._tiger._load_private_key",
    return_value=MagicMock(),
)


class TestTigerSecTypeMapping:
    def test_stk_maps_to_equity(self):
        assert _SEC_TYPE_MAP["STK"] == "equity"

    def test_opt_maps_to_option(self):
        assert _SEC_TYPE_MAP["OPT"] == "option"

    def test_fut_maps_to_futures(self):
        assert _SEC_TYPE_MAP["FUT"] == "futures"

    def test_war_maps_to_warrant(self):
        assert _SEC_TYPE_MAP["WAR"] == "warrant"

    def test_bond_maps_to_fixed_income(self):
        assert _SEC_TYPE_MAP["BOND"] == "fixed_income"


class TestTigerPositionMapping:
    def test_single_position(self):
        adapter = _make_tiger_adapter()
        api_data = _tiger_api_response([_tiger_position()])
        with _MOCK_LOAD_KEY_PATCH, _MOCK_SIGN_PATCH, \
             patch.object(adapter._client, "post", return_value=_mock_response(api_data)):
            result = adapter.fetch_positions()

        assert len(result.holdings) == 1
        h = result.holdings[0]
        assert h.symbol == "AAPL"
        assert h.name == "Apple Inc"
        assert h.asset_class == "equity"
        assert h.notional == 17500.0
        assert h.weight == pytest.approx(1.0)
        assert result.broker == "tiger"
        assert result.account_id == "DU123456"

    def test_empty_positions(self):
        adapter = _make_tiger_adapter()
        api_data = _tiger_api_response([])
        with _MOCK_LOAD_KEY_PATCH, _MOCK_SIGN_PATCH, \
             patch.object(adapter._client, "post", return_value=_mock_response(api_data)):
            result = adapter.fetch_positions()

        assert result.holdings == []

    def test_zero_position_skipped(self):
        adapter = _make_tiger_adapter()
        api_data = _tiger_api_response([
            _tiger_position(symbol="AAPL", market_value=17500, quantity=100),
            _tiger_position(symbol="GOOG", market_value=0, quantity=0),
        ])
        with _MOCK_LOAD_KEY_PATCH, _MOCK_SIGN_PATCH, \
             patch.object(adapter._client, "post", return_value=_mock_response(api_data)):
            result = adapter.fetch_positions()

        assert len(result.holdings) == 1
        assert result.holdings[0].symbol == "AAPL"
        assert len(result.skipped) == 1
        assert "GOOG" in result.skipped[0]

    def test_mixed_currencies_warning(self):
        adapter = _make_tiger_adapter()
        api_data = _tiger_api_response([
            _tiger_position(symbol="AAPL", currency="USD", market_value=17500, quantity=100),
            _tiger_position(symbol="0700", currency="HKD", market_value=76000, quantity=200),
        ])
        with _MOCK_LOAD_KEY_PATCH, _MOCK_SIGN_PATCH, \
             patch.object(adapter._client, "post", return_value=_mock_response(api_data)):
            result = adapter.fetch_positions()

        assert any("Mixed currencies" in w for w in result.warnings)

    def test_weights_sum_to_one(self):
        adapter = _make_tiger_adapter()
        api_data = _tiger_api_response([
            _tiger_position(symbol="AAPL", market_value=50000, quantity=100),
            _tiger_position(symbol="MSFT", market_value=30000, quantity=50),
            _tiger_position(symbol="GOOG", market_value=20000, quantity=30),
        ])
        with _MOCK_LOAD_KEY_PATCH, _MOCK_SIGN_PATCH, \
             patch.object(adapter._client, "post", return_value=_mock_response(api_data)):
            result = adapter.fetch_positions()

        total = sum(h.weight for h in result.holdings)
        assert total == pytest.approx(1.0)


class TestTigerSessionValidation:
    def test_missing_credentials_raises_auth_error(self):
        config = TigerConfig(
            gateway_url="https://openapi.itigerup.com/gateway",
            tiger_id="",
            private_key="",
        )
        adapter = TigerAdapter(config)
        with pytest.raises(BrokerAuthError, match="not configured"):
            adapter.validate_session()

    def test_auth_failure_raises_auth_error(self):
        adapter = _make_tiger_adapter()
        api_data = {"code": 40001, "message": "auth failed"}
        with _MOCK_LOAD_KEY_PATCH, _MOCK_SIGN_PATCH, \
             patch.object(adapter._client, "post", return_value=_mock_response(api_data)):
            with pytest.raises(BrokerAuthError, match="authentication failed"):
                adapter.validate_session()

    def test_unreachable_raises_connection_error(self):
        adapter = _make_tiger_adapter()
        with _MOCK_LOAD_KEY_PATCH, _MOCK_SIGN_PATCH, \
             patch.object(adapter._client, "post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(BrokerConnectionError, match="Cannot reach"):
                adapter.validate_session()

    def test_cryptography_not_installed_raises_broker_error(self):
        config = TigerConfig(
            gateway_url="https://openapi.itigerup.com/gateway",
            tiger_id="test_id",
            private_key="-----BEGIN RSA PRIVATE KEY-----\nfake\n-----END RSA PRIVATE KEY-----",
        )
        adapter = TigerAdapter(config)
        with patch("analyst.portfolio.brokers._tiger._load_private_key", side_effect=BrokerError("requires 'cryptography'")):
            with pytest.raises(BrokerError, match="cryptography"):
                adapter.validate_session()


# ===========================================================================
# Factory Tests
# ===========================================================================


class TestBrokerFactory:
    def test_create_ibkr(self):
        adapter = create_broker_adapter("ibkr", gateway_url="https://test:5000/v1/api")
        assert isinstance(adapter, IBKRClientPortalAdapter)
        assert adapter.broker_name == "ibkr"

    def test_create_longbridge(self):
        adapter = create_broker_adapter(
            "longbridge",
            app_key="k", app_secret="s", access_token="t",
        )
        assert isinstance(adapter, LongbridgeAdapter)
        assert adapter.broker_name == "longbridge"

    def test_create_tiger(self):
        adapter = create_broker_adapter(
            "tiger",
            tiger_id="tid", private_key="pk",
        )
        assert isinstance(adapter, TigerAdapter)
        assert adapter.broker_name == "tiger"

    def test_unknown_broker_raises(self):
        with pytest.raises(ValueError, match="Unknown broker 'schwab'"):
            create_broker_adapter("schwab")

    def test_available_brokers_in_error(self):
        with pytest.raises(ValueError, match="ibkr"):
            create_broker_adapter("nope")
        with pytest.raises(ValueError, match="longbridge"):
            create_broker_adapter("nope")
        with pytest.raises(ValueError, match="tiger"):
            create_broker_adapter("nope")
