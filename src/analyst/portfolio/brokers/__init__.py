from __future__ import annotations

from ._base import BrokerAdapter, BrokerAuthError, BrokerConnectionError, BrokerError, BrokerSyncResult
from ._ibkr import IBKRClientPortalAdapter, IBKRConfig
from ._longbridge import LongbridgeAdapter, LongbridgeConfig
from ._tiger import TigerAdapter, TigerConfig

# Each entry: (AdapterClass, ConfigClass)
# ConfigClass must have a from_env(**kwargs) classmethod.
_BROKER_REGISTRY: dict[str, tuple[type, type]] = {
    "ibkr": (IBKRClientPortalAdapter, IBKRConfig),
    "longbridge": (LongbridgeAdapter, LongbridgeConfig),
    "tiger": (TigerAdapter, TigerConfig),
}


def create_broker_adapter(broker: str = "ibkr", **kwargs: object) -> BrokerAdapter:
    entry = _BROKER_REGISTRY.get(broker)
    if entry is None:
        raise ValueError(
            f"Unknown broker '{broker}'. Available: {', '.join(_BROKER_REGISTRY)}"
        )
    adapter_cls, config_cls = entry
    # Filter out empty-string kwargs so from_env falls back to env vars
    filtered = {k: str(v) for k, v in kwargs.items() if v}
    config = config_cls.from_env(**filtered)
    return adapter_cls(config)


__all__ = [
    "BrokerAdapter",
    "BrokerAuthError",
    "BrokerConnectionError",
    "BrokerError",
    "BrokerSyncResult",
    "IBKRClientPortalAdapter",
    "IBKRConfig",
    "LongbridgeAdapter",
    "LongbridgeConfig",
    "TigerAdapter",
    "TigerConfig",
    "create_broker_adapter",
]
