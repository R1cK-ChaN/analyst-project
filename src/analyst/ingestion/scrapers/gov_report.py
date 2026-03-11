"""Government report scrapers for US, CN, JP, and EU institutions.

Fetches the latest official statistical releases and policy documents from
~40 government sources across four regions, returning structured
GovReportItem records suitable for storage in the news_articles table.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import timezone
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import feedparser
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser
from markdownify import markdownify as md

logger = logging.getLogger(__name__)

_TZINFOS = {
    "UTC": timezone.utc,
    "GMT": timezone.utc,
    "ET": ZoneInfo("America/New_York"),
    "EST": ZoneInfo("America/New_York"),
    "EDT": ZoneInfo("America/New_York"),
}

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GovReportItem:
    source: str            # "gov_bls", "gov_nbs", etc.
    source_id: str         # "us_bls_cpi", "cn_stats_gdp", etc.
    title: str
    url: str
    published_at: str      # ISO 8601 UTC when available, otherwise ISO date
    institution: str       # "BLS", "国家统计局", etc.
    country: str           # "US", "CN", "JP", "EU"
    language: str          # "en", "zh"
    data_category: str     # "inflation", "gdp", etc.
    importance: str = ""   # "high", "medium", "low"
    description: str = ""
    content_markdown: str = ""
    raw_json: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Source configurations
# ---------------------------------------------------------------------------

_US_SOURCES: dict[str, dict] = {
    # -- BLS: fixed URLs -------------------------------------------------
    "us_bls_cpi": {
        "strategy": "fixed_url",
        "url": "https://www.bls.gov/news.release/cpi.htm",
        "institution": "BLS",
        "country": "US",
        "language": "en",
        "data_category": "inflation",
        "importance": "high",
        "default_timezone": "America/New_York",
        "content_selectors": ["#news-release", ".news-release-intro", "#bodytext", "div.body-content"],
        "title_selectors": ["#news-release h2", "#news-release h3", "h1", "title"],
        "datetime_patterns": [
            r"embargoed until\s*([0-9]{1,2}:\d{2}\s*[ap]\.?m\.?\s*(?:\([A-Z]{2,4}\)|[A-Z]{2,4})\s*\w+,\s*\w+\s+\d{1,2},\s*\d{4})",
        ],
        "date_patterns": [
            r"(?:Released|Issued|Published)[:\s]*(\w+ \d{1,2},?\s*\d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
        ],
    },
    "us_bls_ppi": {
        "strategy": "fixed_url",
        "url": "https://www.bls.gov/news.release/ppi.htm",
        "institution": "BLS",
        "country": "US",
        "language": "en",
        "data_category": "inflation",
        "importance": "high",
        "default_timezone": "America/New_York",
        "content_selectors": ["#news-release", ".news-release-intro", "#bodytext", "div.body-content"],
        "title_selectors": ["#news-release h2", "#news-release h3", "h1", "title"],
        "datetime_patterns": [
            r"embargoed until\s*([0-9]{1,2}:\d{2}\s*[ap]\.?m\.?\s*(?:\([A-Z]{2,4}\)|[A-Z]{2,4})\s*\w+,\s*\w+\s+\d{1,2},\s*\d{4})",
        ],
        "date_patterns": [
            r"(?:Released|Issued|Published)[:\s]*(\w+ \d{1,2},?\s*\d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
        ],
    },
    "us_bls_nfp": {
        "strategy": "fixed_url",
        "url": "https://www.bls.gov/news.release/empsit.htm",
        "institution": "BLS",
        "country": "US",
        "language": "en",
        "data_category": "employment",
        "importance": "high",
        "default_timezone": "America/New_York",
        "content_selectors": ["#news-release", ".news-release-intro", "#bodytext", "div.body-content"],
        "title_selectors": ["#news-release h2", "#news-release h3", "h1", "title"],
        "datetime_patterns": [
            r"embargoed until\s*([0-9]{1,2}:\d{2}\s*[ap]\.?m\.?\s*(?:\([A-Z]{2,4}\)|[A-Z]{2,4})\s*\w+,\s*\w+\s+\d{1,2},\s*\d{4})",
        ],
        "date_patterns": [
            r"(?:Released|Issued|Published)[:\s]*(\w+ \d{1,2},?\s*\d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
        ],
    },
    # -- BEA: listing + keywords -----------------------------------------
    "us_bea_gdp": {
        "strategy": "listing_keywords",
        "url": "https://www.bea.gov/news/current-releases",
        "base_url": "https://www.bea.gov",
        "link_must_contain": "/news/",
        "keywords": ["gross domestic product", "gdp"],
        "institution": "BEA",
        "country": "US",
        "language": "en",
        "data_category": "gdp",
        "importance": "high",
        "content_selectors": ["article", ".press-release", ".field--name-body", "#block-bea-content"],
        "title_selectors": ["h1", "article h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "us_bea_pce": {
        "strategy": "listing_keywords",
        "url": "https://www.bea.gov/news/current-releases",
        "base_url": "https://www.bea.gov",
        "link_must_contain": "/news/",
        "keywords": ["personal consumption", "personal income", "pce"],
        "institution": "BEA",
        "country": "US",
        "language": "en",
        "data_category": "inflation",
        "importance": "high",
        "content_selectors": ["article", ".press-release", ".field--name-body", "#block-bea-content"],
        "title_selectors": ["h1", "article h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "us_bea_trade": {
        "strategy": "listing_keywords",
        "url": "https://www.bea.gov/news/current-releases",
        "base_url": "https://www.bea.gov",
        "link_must_contain": "/news/",
        "keywords": ["trade", "international trade", "goods and services"],
        "institution": "BEA",
        "country": "US",
        "language": "en",
        "data_category": "trade",
        "importance": "medium",
        "content_selectors": ["article", ".press-release", ".field--name-body", "#block-bea-content"],
        "title_selectors": ["h1", "article h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    # -- Fed: listing + regex --------------------------------------------
    "us_fed_fomc_statement": {
        "strategy": "listing_regex",
        "url": "https://www.federalreserve.gov/newsevents/pressreleases.htm",
        "base_url": "https://www.federalreserve.gov",
        "link_pattern": r"/newsevents/pressreleases/monetary\d{8}a\.htm",
        "institution": "Federal Reserve",
        "country": "US",
        "language": "en",
        "data_category": "monetary_policy",
        "importance": "high",
        "content_selectors": ["#content", "article", "div.col-xs-12", "#article"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(?:Released|Issued|Date)[:\s]*(\w+ \d{1,2},?\s*\d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "us_fed_fomc_minutes": {
        "strategy": "listing_regex",
        "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        "base_url": "https://www.federalreserve.gov",
        "link_pattern": r"/monetarypolicy/fomcminutes\d{8}\.htm",
        "institution": "Federal Reserve",
        "country": "US",
        "language": "en",
        "data_category": "monetary_policy",
        "importance": "high",
        "content_selectors": ["#content", "article", "div.col-xs-12", "#article"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(?:Released|Issued|Date)[:\s]*(\w+ \d{1,2},?\s*\d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "us_fed_beigebook": {
        "strategy": "listing_regex",
        "url": "https://www.federalreserve.gov/monetarypolicy/beige-book-default.htm",
        "base_url": "https://www.federalreserve.gov",
        "link_pattern": r"/monetarypolicy/beigebook\d{6}\.htm",
        "institution": "Federal Reserve",
        "country": "US",
        "language": "en",
        "data_category": "economic_conditions",
        "importance": "high",
        "content_selectors": ["#content", "article", "div.col-xs-12", "#article"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(?:Released|Issued|Date)[:\s]*(\w+ \d{1,2},?\s*\d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "us_fed_ip": {
        "strategy": "fixed_url",
        "url": "https://www.federalreserve.gov/releases/g17/current/",
        "institution": "Federal Reserve",
        "country": "US",
        "language": "en",
        "data_category": "industrial_production",
        "importance": "medium",
        "content_selectors": ["#content", "article", "div.col-xs-12", "#article"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(?:Released|Issued|Date)[:\s]*(\w+ \d{1,2},?\s*\d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    # -- Census: listing + keywords --------------------------------------
    "us_census_retail": {
        "strategy": "listing_keywords",
        "url": "https://www.census.gov/retail/index.html",
        "base_url": "https://www.census.gov",
        "keywords": ["retail", "advance monthly sales"],
        "institution": "Census Bureau",
        "country": "US",
        "language": "en",
        "data_category": "consumption",
        "importance": "medium",
        "content_selectors": [".press-release", "#content", "article", ".uscb-layout-column-2"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "us_census_housing": {
        "strategy": "listing_keywords",
        "url": "https://www.census.gov/construction/nrc/index.html",
        "base_url": "https://www.census.gov",
        "keywords": ["housing", "new residential", "building permits"],
        "institution": "Census Bureau",
        "country": "US",
        "language": "en",
        "data_category": "housing",
        "importance": "medium",
        "content_selectors": [".press-release", "#content", "article", ".uscb-layout-column-2"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    # -- Treasury: listing + keywords ------------------------------------
    "us_treasury_tic": {
        "strategy": "listing_keywords",
        "url": "https://home.treasury.gov/data/treasury-international-capital-tic-system",
        "base_url": "https://home.treasury.gov",
        "keywords": ["TIC", "treasury international capital", "capital flow"],
        "institution": "Treasury",
        "country": "US",
        "language": "en",
        "data_category": "capital_flows",
        "importance": "medium",
        "content_selectors": ["div.field--name-body", "div.field--type-text-with-summary", "article", "main#content"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "us_treasury_debt": {
        "strategy": "listing_keywords",
        "url": "https://home.treasury.gov/news/press-releases",
        "base_url": "https://home.treasury.gov",
        "keywords": ["debt", "deficit", "fiscal", "budget"],
        "institution": "Treasury",
        "country": "US",
        "language": "en",
        "data_category": "fiscal_policy",
        "importance": "medium",
        "content_selectors": ["div.field--name-body", "div.field--type-text-with-summary", "article", "main#content"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    # -- UMich: fixed URL ------------------------------------------------
    "us_umich_sentiment": {
        "strategy": "fixed_url",
        "url": "https://data.sca.isr.umich.edu/",
        "institution": "UMich",
        "country": "US",
        "language": "en",
        "data_category": "consumer_sentiment",
        "importance": "medium",
        "content_selectors": ["article", ".field-item", "#content", ".main-content"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
}

_CN_SOURCES: dict[str, dict] = {
    # -- NBS: listing + Chinese keywords ---------------------------------
    "cn_nbs_cpi": {
        "strategy": "listing_keywords",
        "url": "https://www.stats.gov.cn/sj/zxfb/",
        "base_url": "https://www.stats.gov.cn/sj/zxfb",
        "keywords": ["居民消费价格", "CPI"],
        "institution": "国家统计局",
        "country": "CN",
        "language": "zh",
        "data_category": "inflation",
        "importance": "high",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.center_xilan", "div.xilan_con", "article"],
        "title_selectors": ["h1", "div.xilan_tit", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{4}/\d{2}/\d{2})",
        ],
    },
    "cn_nbs_ppi": {
        "strategy": "listing_keywords",
        "url": "https://www.stats.gov.cn/sj/zxfb/",
        "base_url": "https://www.stats.gov.cn/sj/zxfb",
        "keywords": ["工业生产者出厂价格", "PPI"],
        "institution": "国家统计局",
        "country": "CN",
        "language": "zh",
        "data_category": "inflation",
        "importance": "high",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.center_xilan", "div.xilan_con", "article"],
        "title_selectors": ["h1", "div.xilan_tit", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{4}/\d{2}/\d{2})",
        ],
    },
    "cn_nbs_gdp": {
        "strategy": "listing_keywords",
        "url": "https://www.stats.gov.cn/sj/zxfb/",
        "base_url": "https://www.stats.gov.cn/sj/zxfb",
        "keywords": ["国内生产总值", "GDP", "国民经济"],
        "institution": "国家统计局",
        "country": "CN",
        "language": "zh",
        "data_category": "gdp",
        "importance": "high",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.center_xilan", "div.xilan_con", "article"],
        "title_selectors": ["h1", "div.xilan_tit", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{4}/\d{2}/\d{2})",
        ],
    },
    "cn_nbs_pmi": {
        "strategy": "listing_keywords",
        "url": "https://www.stats.gov.cn/sj/zxfb/",
        "base_url": "https://www.stats.gov.cn/sj/zxfb",
        "keywords": ["采购经理指数", "PMI"],
        "institution": "国家统计局",
        "country": "CN",
        "language": "zh",
        "data_category": "manufacturing",
        "importance": "high",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.center_xilan", "div.xilan_con", "article"],
        "title_selectors": ["h1", "div.xilan_tit", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{4}/\d{2}/\d{2})",
        ],
    },
    "cn_nbs_industrial": {
        "strategy": "listing_keywords",
        "url": "https://www.stats.gov.cn/sj/zxfb/",
        "base_url": "https://www.stats.gov.cn/sj/zxfb",
        "keywords": ["规模以上工业增加值", "工业增加值"],
        "institution": "国家统计局",
        "country": "CN",
        "language": "zh",
        "data_category": "industrial_production",
        "importance": "medium",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.center_xilan", "div.xilan_con", "article"],
        "title_selectors": ["h1", "div.xilan_tit", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{4}/\d{2}/\d{2})",
        ],
    },
    "cn_nbs_retail": {
        "strategy": "listing_keywords",
        "url": "https://www.stats.gov.cn/sj/zxfb/",
        "base_url": "https://www.stats.gov.cn/sj/zxfb",
        "keywords": ["社会消费品零售总额", "消费品零售"],
        "institution": "国家统计局",
        "country": "CN",
        "language": "zh",
        "data_category": "consumption",
        "importance": "medium",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.center_xilan", "div.xilan_con", "article"],
        "title_selectors": ["h1", "div.xilan_tit", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{4}/\d{2}/\d{2})",
        ],
    },
    "cn_nbs_fai": {
        "strategy": "listing_keywords",
        "url": "https://www.stats.gov.cn/sj/zxfb/",
        "base_url": "https://www.stats.gov.cn/sj/zxfb",
        "keywords": ["固定资产投资", "投资"],
        "institution": "国家统计局",
        "country": "CN",
        "language": "zh",
        "data_category": "investment",
        "importance": "medium",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.center_xilan", "div.xilan_con", "article"],
        "title_selectors": ["h1", "div.xilan_tit", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
            r"(\d{4}/\d{2}/\d{2})",
        ],
    },
    # -- PBOC: listing + keywords ----------------------------------------
    "cn_pboc_monetary": {
        "strategy": "listing_keywords",
        "url": "http://www.pbc.gov.cn/diaochatongjisi/116219/116319/index.html",
        "base_url": "http://www.pbc.gov.cn",
        "keywords": ["社会融资规模", "M2", "货币供应量", "金融统计"],
        "institution": "中国人民银行",
        "country": "CN",
        "language": "zh",
        "data_category": "monetary",
        "importance": "high",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.content", "article"],
        "title_selectors": ["h1", "div.tit", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "cn_pboc_lpr": {
        "strategy": "listing_keywords",
        "url": "http://www.pbc.gov.cn/zhengcehuobisi/125207/125213/125440/index.html",
        "base_url": "http://www.pbc.gov.cn",
        "keywords": ["贷款市场报价利率", "LPR"],
        "institution": "中国人民银行",
        "country": "CN",
        "language": "zh",
        "data_category": "interest_rate",
        "importance": "high",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.content", "article"],
        "title_selectors": ["h1", "div.tit", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    # -- Customs: listing + keywords -------------------------------------
    "cn_customs_trade": {
        "strategy": "listing_keywords",
        "url": "http://www.customs.gov.cn/customs/302249/zfxxgk/2799825/302274/302275/index.html",
        "base_url": "http://www.customs.gov.cn",
        "keywords": ["进出口", "外贸", "贸易"],
        "institution": "海关总署",
        "country": "CN",
        "language": "zh",
        "data_category": "trade",
        "importance": "high",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.easysite-news-text", "article"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    # -- MOF: listing + keywords -----------------------------------------
    "cn_mof_fiscal": {
        "strategy": "listing_keywords",
        "url": "https://www.mof.gov.cn/zhengwuxinxi/caizhengshuju/",
        "base_url": "https://www.mof.gov.cn",
        "keywords": ["财政收入", "财政支出", "财政数据", "一般公共预算"],
        "institution": "财政部",
        "country": "CN",
        "language": "zh",
        "data_category": "fiscal_policy",
        "importance": "medium",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.article-content", "div.content", "article"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "cn_mof_bonds": {
        "strategy": "listing_keywords",
        "url": "https://gks.mof.gov.cn/ztztz/guozaiguanli/",
        "base_url": "https://gks.mof.gov.cn/ztztz/guozaiguanli",
        "keywords": ["国债", "地方政府债", "债券", "发行"],
        "institution": "财政部",
        "country": "CN",
        "language": "zh",
        "data_category": "bond_issuance",
        "importance": "medium",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.article-content", "div.content", "article"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    # -- SAFE: listing + keywords ----------------------------------------
    "cn_safe_fx": {
        "strategy": "listing_keywords",
        "url": "https://www.safe.gov.cn/safe/whcb/index.html",
        "base_url": "https://www.safe.gov.cn/safe/whcb",
        "keywords": ["外汇储备", "储备规模"],
        "institution": "国家外汇管理局",
        "country": "CN",
        "language": "zh",
        "data_category": "fx_reserves",
        "importance": "medium",
        "encoding": "utf-8",
        "content_selectors": ["div.TRS_Editor", "div#zoom", "div.content", "article"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\d{4})年(\d{1,2})月(\d{1,2})日",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    # -- Caixin / S&P Global: listing + keywords -------------------------
    "cn_caixin_pmi": {
        "strategy": "listing_keywords",
        "url": "https://www.pmi.spglobal.com/Public/Home/PressRelease",
        "base_url": "https://www.pmi.spglobal.com",
        "keywords": ["caixin"],
        "extra_keywords": ["pmi", "china"],
        "institution": "Caixin/S&P Global",
        "country": "CN",
        "language": "en",
        "data_category": "manufacturing",
        "importance": "high",
        "content_selectors": [".press-release-body", "article", ".content-area", "#content"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
}

_JP_SOURCES: dict[str, dict] = {
    "jp_boj_statement": {
        "strategy": "listing_regex",
        "url": "https://www.boj.or.jp/en/mopo/mpmdeci/index.htm",
        "base_url": "https://www.boj.or.jp",
        "link_pattern": r"/en/mopo/mpmdeci/mpr_\d+/",
        "institution": "Bank of Japan",
        "country": "JP",
        "language": "en",
        "data_category": "monetary_policy",
        "importance": "high",
        "content_selectors": ["div#main", "div.releaseMain", "div.mb20", "article", "main"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}/\d{2}/\d{2})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "jp_boj_outlook": {
        "strategy": "listing_regex",
        "url": "https://www.boj.or.jp/en/mopo/outlook/index.htm",
        "base_url": "https://www.boj.or.jp",
        "link_pattern": r"/en/mopo/outlook/aar\d+",
        "institution": "Bank of Japan",
        "country": "JP",
        "language": "en",
        "data_category": "monetary_policy",
        "importance": "high",
        "content_selectors": ["div#main", "div.releaseMain", "div.mb20", "article", "main"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}/\d{2}/\d{2})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "jp_boj_minutes": {
        "strategy": "listing_regex",
        "url": "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm",
        "base_url": "https://www.boj.or.jp",
        "link_pattern": r"/en/mopo/mpmsche_minu/opinion_\d+/",
        "institution": "Bank of Japan",
        "country": "JP",
        "language": "en",
        "data_category": "monetary_policy",
        "importance": "high",
        "content_selectors": ["div#main", "div.releaseMain", "div.mb20", "article", "main"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}/\d{2}/\d{2})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "jp_cao_gdp": {
        "strategy": "listing_regex",
        "url": "https://www.esri.cao.go.jp/en/sna/sokuhou/sokuhou_top.html",
        "base_url": "https://www.esri.cao.go.jp",
        "link_pattern": r"/en/sna/data/sokuhou/.*qe\d+",
        "institution": "Cabinet Office",
        "country": "JP",
        "language": "en",
        "data_category": "gdp",
        "importance": "high",
        "content_selectors": ["div#main", "div.releaseMain", "div.mb20", "article", "main"],
        "title_selectors": ["h1", "h2", "title"],
        "date_patterns": [
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}/\d{2}/\d{2})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
}

_EU_SOURCES: dict[str, dict] = {
    # -- ECB: listing + regex --------------------------------------------
    "eu_ecb_statement": {
        "strategy": "listing_regex",
        "url": "https://www.ecb.europa.eu/press/pr/html/index.en.html",
        "base_url": "https://www.ecb.europa.eu",
        "link_pattern": r"/press/pr/date/\d{4}/html/.*\.en\.html",
        "institution": "ECB",
        "country": "EU",
        "language": "en",
        "data_category": "monetary_policy",
        "importance": "high",
        "content_selectors": [
            "div.ecb-pressContent", "article.ecb-publicationPage",
            "div.definition", "div#main-wrapper", ".main-content", "main", "article",
        ],
        "title_selectors": ["h1.ecb-pressHeadline", "h1", "h2", "title"],
        "date_patterns": [
            r"(\d{1,2} \w+ \d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{1,2} \w{3} \d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "eu_ecb_minutes": {
        "strategy": "listing_regex",
        "url": "https://www.ecb.europa.eu/press/accounts/html/index.en.html",
        "base_url": "https://www.ecb.europa.eu",
        "link_pattern": r"/press/accounts/\d{4}/html/.*\.en\.html",
        "institution": "ECB",
        "country": "EU",
        "language": "en",
        "data_category": "monetary_policy",
        "importance": "high",
        "content_selectors": [
            "div.ecb-pressContent", "article.ecb-publicationPage",
            "div.definition", "div#main-wrapper", ".main-content", "main", "article",
        ],
        "title_selectors": ["h1.ecb-pressHeadline", "h1", "h2", "title"],
        "date_patterns": [
            r"(\d{1,2} \w+ \d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{1,2} \w{3} \d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "eu_ecb_bulletin": {
        "strategy": "listing_regex",
        "url": "https://www.ecb.europa.eu/pub/economic-bulletin/html/index.en.html",
        "base_url": "https://www.ecb.europa.eu",
        "link_pattern": r"/pub/economic-bulletin/html/eb\d+\.en\.html",
        "institution": "ECB",
        "country": "EU",
        "language": "en",
        "data_category": "economic_conditions",
        "importance": "medium",
        "content_selectors": [
            "div.ecb-pressContent", "article.ecb-publicationPage",
            "div.pub-section", "div#content", ".main-content", "main", "article",
        ],
        "title_selectors": ["h1.ecb-pressHeadline", "h1", "h2", "title"],
        "date_patterns": [
            r"(\d{1,2} \w+ \d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    # -- ECB RSS sources -------------------------------------------------
    "eu_ecb_press": {
        "strategy": "rss",
        "url": "https://www.ecb.europa.eu/rss/press.html",
        "base_url": "https://www.ecb.europa.eu",
        "institution": "ECB",
        "country": "EU",
        "language": "en",
        "data_category": "press_releases",
        "importance": "medium",
        "content_selectors": [
            "div.ecb-pressContent", "article.ecb-publicationPage",
            ".main-content", "main", "article",
        ],
        "title_selectors": ["h1.ecb-pressHeadline", "h1", "h2", "title"],
        "date_patterns": [
            r"(\d{1,2} \w+ \d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "eu_ecb_speeches": {
        "strategy": "rss",
        "url": "https://www.ecb.europa.eu/rss/speeches.html",
        "base_url": "https://www.ecb.europa.eu",
        "institution": "ECB",
        "country": "EU",
        "language": "en",
        "data_category": "speeches",
        "importance": "medium",
        "content_selectors": [
            "div.ecb-pressContent", "article.ecb-publicationPage",
            ".main-content", "main", "article",
        ],
        "title_selectors": ["h1.ecb-pressHeadline", "h1", "h2", "title"],
        "date_patterns": [
            r"(\d{1,2} \w+ \d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    # -- Eurostat: listing + keywords ------------------------------------
    "eu_eurostat_cpi": {
        "strategy": "listing_keywords",
        "url": "https://ec.europa.eu/eurostat/web/products-eurostat-news",
        "base_url": "https://ec.europa.eu",
        "keywords": ["HICP", "inflation", "consumer price"],
        "institution": "Eurostat",
        "country": "EU",
        "language": "en",
        "data_category": "inflation",
        "importance": "medium",
        "content_selectors": [
            "div.stat-news-release-content", "div.article-body",
            "div#main-content", "article", "main",
        ],
        "title_selectors": ["h1.stat-news-release-title", "h1", "h2", "title"],
        "date_patterns": [
            r"(\d{1,2} \w+ \d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "eu_eurostat_gdp": {
        "strategy": "listing_keywords",
        "url": "https://ec.europa.eu/eurostat/web/products-eurostat-news",
        "base_url": "https://ec.europa.eu",
        "keywords": ["GDP", "gross domestic product", "economic growth"],
        "institution": "Eurostat",
        "country": "EU",
        "language": "en",
        "data_category": "gdp",
        "importance": "medium",
        "content_selectors": [
            "div.stat-news-release-content", "div.article-body",
            "div#main-content", "article", "main",
        ],
        "title_selectors": ["h1.stat-news-release-title", "h1", "h2", "title"],
        "date_patterns": [
            r"(\d{1,2} \w+ \d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
    "eu_eurostat_employment": {
        "strategy": "listing_keywords",
        "url": "https://ec.europa.eu/eurostat/web/products-eurostat-news",
        "base_url": "https://ec.europa.eu",
        "keywords": ["unemployment", "employment", "labour market"],
        "institution": "Eurostat",
        "country": "EU",
        "language": "en",
        "data_category": "employment",
        "importance": "medium",
        "content_selectors": [
            "div.stat-news-release-content", "div.article-body",
            "div#main-content", "article", "main",
        ],
        "title_selectors": ["h1.stat-news-release-title", "h1", "h2", "title"],
        "date_patterns": [
            r"(\d{1,2} \w+ \d{4})",
            r"(\w+ \d{1,2},?\s*\d{4})",
            r"(\d{4}-\d{2}-\d{2})",
        ],
    },
}

# ---------------------------------------------------------------------------
# Shared parsing helpers
# ---------------------------------------------------------------------------

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_NOISE_SELECTORS = ["script", "style", "nav", "noscript", "header", "footer", "iframe"]
_NOISE_CLASSES = [
    ".breadcrumb", ".pagination", ".social-share", ".sidebar",
    "#sidebar", ".nav", ".menu", ".footer", ".header",
]


def _get_html(
    session: requests.Session,
    url: str,
    *,
    timeout: int = 30,
    encoding: str | None = None,
) -> str:
    """Fetch a URL and return its HTML as a string."""
    resp = session.get(url, timeout=timeout)
    resp.raise_for_status()
    if encoding:
        resp.encoding = encoding
    return resp.text


def _extract_content(html: str, selectors: list[str]) -> str:
    """Extract the main content region via CSS selector priority list.

    Returns inner HTML of the first matching selector after removing noise
    elements. Falls back to <body> if no selector matches.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_NOISE_SELECTORS):
        tag.decompose()
    for sel in _NOISE_CLASSES:
        for el in soup.select(sel):
            el.decompose()

    for selector in selectors:
        match = soup.select_one(selector)
        if match:
            return str(match)
    body = soup.find("body")
    return str(body) if body else html


def _extract_title(html: str, selectors: list[str]) -> str:
    """Extract the page title using a selector priority list."""
    soup = BeautifulSoup(html, "html.parser")
    for selector in selectors:
        match = soup.select_one(selector)
        if match:
            text = match.get_text(strip=True)
            if text:
                return text
    title_tag = soup.find("title")
    return title_tag.get_text(strip=True) if title_tag else ""


def _extract_date_en(html: str, patterns: list[str]) -> str | None:
    """Extract a publication date via regex patterns, return YYYY-MM-DD or None."""
    for pattern in patterns:
        m = re.search(pattern, html)
        if m:
            raw = m.group(1) if m.lastindex else m.group(0)
            try:
                dt = dateutil_parser.parse(raw, fuzzy=True)
                return dt.strftime("%Y-%m-%d")
            except (ValueError, OverflowError):
                continue
    return None


def _extract_datetime_en(
    html: str,
    patterns: list[str],
    *,
    default_timezone: str = "UTC",
) -> str | None:
    """Extract an English publication datetime and normalize to UTC ISO."""
    for pattern in patterns:
        m = re.search(pattern, html, re.I | re.S)
        if not m:
            continue
        raw = m.group(1) if m.lastindex else m.group(0)
        cleaned = re.sub(r"\(([A-Z]{2,4})\)", r" \1 ", raw)
        cleaned = re.sub(r"\ba\.m\.\b", "am", cleaned, flags=re.I)
        cleaned = re.sub(r"\bp\.m\.\b", "pm", cleaned, flags=re.I)
        try:
            dt = dateutil_parser.parse(cleaned, fuzzy=True, tzinfos=_TZINFOS)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(default_timezone))
            return dt.astimezone(timezone.utc).isoformat()
        except (ValueError, OverflowError):
            continue
    return None


def _extract_date_cn(html: str) -> str | None:
    """Extract a publication date from Chinese gov pages.

    Priority: <meta name="PubDate"> → 年月日 regex → slash format.
    """
    # Meta tag first
    m = re.search(r'<meta\s+name=["\']PubDate["\']\s+content=["\']([^"\']+)["\']', html, re.I)
    if m:
        raw = m.group(1).strip()
        try:
            dt = dateutil_parser.parse(raw, fuzzy=True)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, OverflowError):
            pass

    # Chinese date: 2024年3月15日
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", html)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # Slash format: 2024/03/15
    m = re.search(r"(\d{4})/(\d{2})/(\d{2})", html)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    return None


def _html_to_markdown(html: str, *, max_chars: int = 15_000) -> str:
    """Convert HTML to clean markdown, stripping noise."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_NOISE_SELECTORS):
        tag.decompose()
    for sel in _NOISE_CLASSES:
        for el in soup.select(sel):
            el.decompose()
    # Remove comments
    from bs4 import Comment
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    text = md(str(soup), heading_style="ATX", strip=["img"])
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"  +", " ", text)
    return text.strip()[:max_chars]


def _resolve_url(href: str, base_url: str) -> str:
    """Convert a potentially relative URL to absolute."""
    if href.startswith(("http://", "https://")):
        return href
    return urljoin(base_url + "/", href)


def _link_matches_keywords(
    tag: BeautifulSoup,
    keywords: list[str],
    extra_keywords: list[str] | None = None,
) -> bool:
    """Check if an <a> tag's text (+ href) matches keyword criteria."""
    text = (tag.get_text(" ", strip=True) + " " + tag.get("href", "")).lower()
    primary_match = any(kw.lower() in text for kw in keywords)
    if not primary_match:
        return False
    if extra_keywords:
        return any(ek.lower() in text for ek in extra_keywords)
    return True


# ---------------------------------------------------------------------------
# Region client classes
# ---------------------------------------------------------------------------


class USGovReportClient:
    """Scraper for US government institution reports."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})

    def fetch_all(self) -> list[GovReportItem]:
        items: list[GovReportItem] = []
        for source_id, cfg in _US_SOURCES.items():
            try:
                item = self._fetch_source(source_id, cfg)
                if item:
                    items.append(item)
            except Exception:
                logger.warning("US gov report fetch failed: %s", source_id, exc_info=True)
            time.sleep(1.0)
        return items

    def _fetch_source(self, source_id: str, cfg: dict) -> GovReportItem | None:
        strategy = cfg["strategy"]
        if strategy == "fixed_url":
            return self._fetch_fixed_url(source_id, cfg)
        if strategy == "listing_keywords":
            return self._fetch_listing_keywords(source_id, cfg)
        if strategy == "listing_regex":
            return self._fetch_listing_regex(source_id, cfg)
        return None

    def _fetch_fixed_url(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        title = _extract_title(html, cfg["title_selectors"])
        published_at = _extract_datetime_en(
            html,
            cfg.get("datetime_patterns", []),
            default_timezone=cfg.get("default_timezone", "UTC"),
        ) or _extract_date_en(html, cfg["date_patterns"])
        content_html = _extract_content(html, cfg["content_selectors"])
        content_md = _html_to_markdown(content_html)
        if not title:
            return None
        return GovReportItem(
            source=f"gov_{cfg['institution'].lower().replace(' ', '_')}",
            source_id=source_id,
            title=title,
            url=cfg["url"],
            published_at=published_at or "",
            institution=cfg["institution"],
            country=cfg["country"],
            language=cfg["language"],
            data_category=cfg["data_category"],
            importance=cfg.get("importance", ""),
            content_markdown=content_md,
        )

    def _fetch_listing_keywords(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])
        keywords = cfg["keywords"]
        extra_keywords = cfg.get("extra_keywords")
        link_must_contain = cfg.get("link_must_contain")

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if link_must_contain and link_must_contain not in href:
                continue
            if _link_matches_keywords(a_tag, keywords, extra_keywords):
                if href.endswith(".pdf"):
                    continue
                detail_url = _resolve_url(href, base_url)
                return self._fetch_detail_page(source_id, cfg, detail_url)
        return None

    def _fetch_listing_regex(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])
        pattern = re.compile(cfg["link_pattern"])

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if pattern.search(href):
                detail_url = _resolve_url(href, base_url)
                return self._fetch_detail_page(source_id, cfg, detail_url)
        return None

    def _fetch_detail_page(self, source_id: str, cfg: dict, url: str) -> GovReportItem | None:
        html = _get_html(self.session, url)
        title = _extract_title(html, cfg["title_selectors"])
        published_at = _extract_datetime_en(
            html,
            cfg.get("datetime_patterns", []),
            default_timezone=cfg.get("default_timezone", "UTC"),
        ) or _extract_date_en(html, cfg["date_patterns"])
        content_html = _extract_content(html, cfg["content_selectors"])
        content_md = _html_to_markdown(content_html)
        if not title:
            return None
        return GovReportItem(
            source=f"gov_{cfg['institution'].lower().replace(' ', '_')}",
            source_id=source_id,
            title=title,
            url=url,
            published_at=published_at or "",
            institution=cfg["institution"],
            country=cfg["country"],
            language=cfg["language"],
            data_category=cfg["data_category"],
            importance=cfg.get("importance", ""),
            content_markdown=content_md,
        )


class CNGovReportClient:
    """Scraper for Chinese government institution reports."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})

    def fetch_all(self) -> list[GovReportItem]:
        items: list[GovReportItem] = []
        for source_id, cfg in _CN_SOURCES.items():
            try:
                item = self._fetch_source(source_id, cfg)
                if item:
                    items.append(item)
            except Exception:
                logger.warning("CN gov report fetch failed: %s", source_id, exc_info=True)
            time.sleep(1.0)
        return items

    def _fetch_source(self, source_id: str, cfg: dict) -> GovReportItem | None:
        strategy = cfg["strategy"]
        if strategy == "listing_keywords":
            return self._fetch_listing_keywords(source_id, cfg)
        return None

    def _fetch_listing_keywords(self, source_id: str, cfg: dict) -> GovReportItem | None:
        encoding = cfg.get("encoding", "utf-8")
        html = _get_html(self.session, cfg["url"], encoding=encoding)
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])
        keywords = cfg["keywords"]
        extra_keywords = cfg.get("extra_keywords")

        link_must_contain = cfg.get("link_must_contain")

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if link_must_contain and link_must_contain not in href:
                continue
            if _link_matches_keywords(a_tag, keywords, extra_keywords):
                if href.endswith(".pdf"):
                    continue
                detail_url = _resolve_url(href, base_url)
                return self._fetch_detail_page(source_id, cfg, detail_url, encoding)
        return None

    def _fetch_detail_page(
        self, source_id: str, cfg: dict, url: str, encoding: str
    ) -> GovReportItem | None:
        html = _get_html(self.session, url, encoding=encoding)
        title = _extract_title(html, cfg["title_selectors"])
        date = _extract_date_cn(html)
        if not date:
            date = _extract_date_en(html, cfg["date_patterns"])
        content_html = _extract_content(html, cfg["content_selectors"])
        content_md = _html_to_markdown(content_html)
        if not title:
            return None
        return GovReportItem(
            source=f"gov_{cfg['institution'].lower().replace(' ', '_')}",
            source_id=source_id,
            title=title,
            url=url,
            published_at=date or "",
            institution=cfg["institution"],
            country=cfg["country"],
            language=cfg["language"],
            data_category=cfg["data_category"],
            importance=cfg.get("importance", ""),
            content_markdown=content_md,
        )


class JPGovReportClient:
    """Scraper for Japanese government institution reports."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})

    def fetch_all(self) -> list[GovReportItem]:
        items: list[GovReportItem] = []
        for source_id, cfg in _JP_SOURCES.items():
            try:
                item = self._fetch_source(source_id, cfg)
                if item:
                    items.append(item)
            except Exception:
                logger.warning("JP gov report fetch failed: %s", source_id, exc_info=True)
            time.sleep(1.0)
        return items

    def _fetch_source(self, source_id: str, cfg: dict) -> GovReportItem | None:
        strategy = cfg["strategy"]
        if strategy == "listing_regex":
            return self._fetch_listing_regex(source_id, cfg)
        return None

    def _fetch_listing_regex(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])
        pattern = re.compile(cfg["link_pattern"])

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if pattern.search(href):
                if href.endswith(".pdf"):
                    continue
                detail_url = _resolve_url(href, base_url)
                return self._fetch_detail_page(source_id, cfg, detail_url)
        return None

    def _fetch_detail_page(self, source_id: str, cfg: dict, url: str) -> GovReportItem | None:
        html = _get_html(self.session, url)
        title = _extract_title(html, cfg["title_selectors"])
        date = _extract_date_en(html, cfg["date_patterns"])
        content_html = _extract_content(html, cfg["content_selectors"])
        content_md = _html_to_markdown(content_html)
        if not title:
            return None
        return GovReportItem(
            source=f"gov_{cfg['institution'].lower().replace(' ', '_')}",
            source_id=source_id,
            title=title,
            url=url,
            published_at=date or "",
            institution=cfg["institution"],
            country=cfg["country"],
            language=cfg["language"],
            data_category=cfg["data_category"],
            importance=cfg.get("importance", ""),
            content_markdown=content_md,
        )


class EUGovReportClient:
    """Scraper for EU institution reports (ECB, Eurostat)."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": _USER_AGENT})

    def fetch_all(self) -> list[GovReportItem]:
        items: list[GovReportItem] = []
        for source_id, cfg in _EU_SOURCES.items():
            try:
                item = self._fetch_source(source_id, cfg)
                if item:
                    items.append(item)
            except Exception:
                logger.warning("EU gov report fetch failed: %s", source_id, exc_info=True)
            time.sleep(1.0)
        return items

    def _fetch_source(self, source_id: str, cfg: dict) -> GovReportItem | None:
        strategy = cfg["strategy"]
        if strategy == "listing_regex":
            return self._fetch_listing_regex(source_id, cfg)
        if strategy == "listing_keywords":
            return self._fetch_listing_keywords(source_id, cfg)
        if strategy == "rss":
            return self._fetch_rss(source_id, cfg)
        return None

    def _fetch_listing_regex(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])
        pattern = re.compile(cfg["link_pattern"])

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if pattern.search(href):
                detail_url = _resolve_url(href, base_url)
                return self._fetch_detail_page(source_id, cfg, detail_url)
        return None

    def _fetch_listing_keywords(self, source_id: str, cfg: dict) -> GovReportItem | None:
        html = _get_html(self.session, cfg["url"])
        soup = BeautifulSoup(html, "html.parser")
        base_url = cfg.get("base_url", cfg["url"])
        keywords = cfg["keywords"]

        for a_tag in soup.find_all("a", href=True):
            if _link_matches_keywords(a_tag, keywords):
                href = a_tag["href"]
                detail_url = _resolve_url(href, base_url)
                return self._fetch_detail_page(source_id, cfg, detail_url)
        return None

    def _fetch_rss(self, source_id: str, cfg: dict) -> GovReportItem | None:
        parsed = feedparser.parse(cfg["url"])
        if not parsed.entries:
            return None
        entry = parsed.entries[0]
        link = entry.get("link", "")
        if not link:
            return None

        title = entry.get("title", "")
        published = entry.get("published", "")
        date = None
        if published:
            try:
                dt = dateutil_parser.parse(published, fuzzy=True)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                date = dt.astimezone(timezone.utc).isoformat()
            except (ValueError, OverflowError):
                pass

        # Try to scrape the full page
        try:
            detail = self._fetch_detail_page(source_id, cfg, link)
            if detail:
                # Prefer RSS title and date if detail page extraction was weak
                return GovReportItem(
                    source=detail.source,
                    source_id=detail.source_id,
                    title=detail.title or title,
                    url=detail.url,
                    published_at=detail.published_at or date or "",
                    institution=detail.institution,
                    country=detail.country,
                    language=detail.language,
                    data_category=detail.data_category,
                    importance=detail.importance,
                    content_markdown=detail.content_markdown,
                )
        except Exception:
            pass

        # Fallback: use RSS metadata only
        summary = BeautifulSoup(
            entry.get("summary", ""), "html.parser"
        ).get_text(" ", strip=True)
        return GovReportItem(
            source=f"gov_{cfg['institution'].lower()}",
            source_id=source_id,
            title=title,
            url=link,
            published_at=date or "",
            institution=cfg["institution"],
            country=cfg["country"],
            language=cfg["language"],
            data_category=cfg["data_category"],
            importance=cfg.get("importance", ""),
            description=summary,
        )

    def _fetch_detail_page(self, source_id: str, cfg: dict, url: str) -> GovReportItem | None:
        html = _get_html(self.session, url)
        title = _extract_title(html, cfg["title_selectors"])
        date = _extract_date_en(html, cfg["date_patterns"])
        content_html = _extract_content(html, cfg["content_selectors"])
        content_md = _html_to_markdown(content_html)
        if not title:
            return None
        return GovReportItem(
            source=f"gov_{cfg['institution'].lower()}",
            source_id=source_id,
            title=title,
            url=url,
            published_at=date or "",
            institution=cfg["institution"],
            country=cfg["country"],
            language=cfg["language"],
            data_category=cfg["data_category"],
            importance=cfg.get("importance", ""),
            content_markdown=content_md,
        )


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class GovReportClient:
    """Unified facade for all government report scrapers."""

    def __init__(self) -> None:
        self.us = USGovReportClient()
        self.cn = CNGovReportClient()
        self.jp = JPGovReportClient()
        self.eu = EUGovReportClient()

    def fetch_all(self) -> list[GovReportItem]:
        items: list[GovReportItem] = []
        for region_client, label in [
            (self.us, "US"),
            (self.cn, "CN"),
            (self.jp, "JP"),
            (self.eu, "EU"),
        ]:
            try:
                items.extend(region_client.fetch_all())
            except Exception:
                logger.warning("Gov report region fetch failed: %s", label, exc_info=True)
        return items

    def fetch_us(self) -> list[GovReportItem]:
        return self.us.fetch_all()

    def fetch_cn(self) -> list[GovReportItem]:
        return self.cn.fetch_all()

    def fetch_jp(self) -> list[GovReportItem]:
        return self.jp.fetch_all()

    def fetch_eu(self) -> list[GovReportItem]:
        return self.eu.fetch_all()
