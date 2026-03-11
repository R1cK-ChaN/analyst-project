"""Site scrapers – calendar, news, indicators, and market data."""

from ._common import ScrapedIndicator, ScrapedMarketQuote, ScrapedNewsItem
from .forexfactory import ForexFactoryCalendarClient, ForexFactoryNewsClient
from .investing import InvestingCalendarClient, InvestingNewsClient
from .bloomberg import BloombergArticle, BloombergArticleClient, BloombergNewsClient
from .ft import FTArticle, FTArticleClient, FTNewsClient
from .reuters import ReutersArticle, ReutersArticleClient, ReutersNewsClient
from .wsj import WSJArticle, WSJArticleClient, WSJNewsClient
from .gov_report import GovReportClient, GovReportItem
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
    "FTArticle",
    "FedMeetingProbability",
    "FedRateProbability",
    "GovReportClient",
    "GovReportItem",
    "NYFedRate",
    "ReutersArticle",
    "ScrapedIndicator",
    "ScrapedMarketQuote",
    "ScrapedNewsItem",
    "WSJArticle",
    # Calendar
    "ForexFactoryCalendarClient",
    "InvestingCalendarClient",
    "TradingEconomicsCalendarClient",
    # News
    "BloombergNewsClient",
    "FTNewsClient",
    "ForexFactoryNewsClient",
    "InvestingNewsClient",
    "ReutersNewsClient",
    "TradingEconomicsNewsClient",
    "WSJNewsClient",
    # Articles
    "BloombergArticleClient",
    "FTArticleClient",
    "ReutersArticleClient",
    "WSJArticleClient",
    # Indicators & Markets
    "TradingEconomicsIndicatorsClient",
    "TradingEconomicsMarketsClient",
    # Rate Probabilities & Reference Rates
    "NYFedRatesClient",
    "RateProbabilityClient",
]
