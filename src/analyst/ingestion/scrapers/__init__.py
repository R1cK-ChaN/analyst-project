"""Site scrapers – calendar, news, indicators, and market data."""

from ._common import ScrapedIndicator, ScrapedMarketQuote, ScrapedNewsItem
from .forexfactory import ForexFactoryCalendarClient, ForexFactoryNewsClient
from .investing import InvestingCalendarClient, InvestingNewsClient
from .bloomberg import BloombergArticle, BloombergArticleClient, BloombergNewsClient
from .reuters import ReutersArticle, ReutersArticleClient, ReutersNewsClient
from .nyfed import NYFedRate, NYFedRatesClient
from .rateprobability import (
    FedMeetingProbability,
    FedRateProbability,
    RateProbabilityClient,
)
from .tradingeconomics import (
    TradingEconomicsCalendarClient,
    TradingEconomicsIndicatorsClient,
    TradingEconomicsMarketsClient,
    TradingEconomicsNewsClient,
)

__all__ = [
    # Data classes
    "BloombergArticle",
    "FedMeetingProbability",
    "FedRateProbability",
    "NYFedRate",
    "ReutersArticle",
    "ScrapedIndicator",
    "ScrapedMarketQuote",
    "ScrapedNewsItem",
    # Calendar
    "ForexFactoryCalendarClient",
    "InvestingCalendarClient",
    "TradingEconomicsCalendarClient",
    # News
    "BloombergNewsClient",
    "ForexFactoryNewsClient",
    "InvestingNewsClient",
    "ReutersNewsClient",
    "TradingEconomicsNewsClient",
    # Articles
    "BloombergArticleClient",
    "ReutersArticleClient",
    # Indicators & Markets
    "TradingEconomicsIndicatorsClient",
    "TradingEconomicsMarketsClient",
    # Rate Probabilities & Reference Rates
    "NYFedRatesClient",
    "RateProbabilityClient",
]
