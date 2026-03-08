"""Site scrapers – calendar, news, indicators, and market data."""

from ._common import ScrapedIndicator, ScrapedMarketQuote, ScrapedNewsItem
from .forexfactory import ForexFactoryCalendarClient, ForexFactoryNewsClient
from .investing import InvestingCalendarClient, InvestingNewsClient
from .reuters import ReutersArticle, ReutersArticleClient, ReutersNewsClient
from .tradingeconomics import (
    TradingEconomicsCalendarClient,
    TradingEconomicsIndicatorsClient,
    TradingEconomicsMarketsClient,
    TradingEconomicsNewsClient,
)

__all__ = [
    # Data classes
    "ReutersArticle",
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
    "ReutersNewsClient",
    "TradingEconomicsNewsClient",
    # Articles
    "ReutersArticleClient",
    # Indicators & Markets
    "TradingEconomicsIndicatorsClient",
    "TradingEconomicsMarketsClient",
]
