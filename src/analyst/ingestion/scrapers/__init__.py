"""Site scrapers – calendar, news, indicators, and market data."""

from ._common import ScrapedIndicator, ScrapedMarketQuote, ScrapedNewsItem
from .forexfactory import ForexFactoryCalendarClient, ForexFactoryNewsClient
from .investing import InvestingCalendarClient, InvestingNewsClient
from .tradingeconomics import (
    TradingEconomicsCalendarClient,
    TradingEconomicsIndicatorsClient,
    TradingEconomicsMarketsClient,
    TradingEconomicsNewsClient,
)

__all__ = [
    # Data classes
    "ScrapedIndicator",
    "ScrapedMarketQuote",
    "ScrapedNewsItem",
    # Calendar
    "ForexFactoryCalendarClient",
    "InvestingCalendarClient",
    "TradingEconomicsCalendarClient",
    # News
    "ForexFactoryNewsClient",
    "InvestingNewsClient",
    "TradingEconomicsNewsClient",
    # Indicators & Markets
    "TradingEconomicsIndicatorsClient",
    "TradingEconomicsMarketsClient",
]
