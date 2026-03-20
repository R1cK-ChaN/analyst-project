from __future__ import annotations

# ── Observation family seed data ─────────────────────────────────────

_FRED_FAMILY_MAP: dict[str, tuple[str, str, str, str, str]] = {
    # series_id: (family_id, canonical_name, unit, frequency, seasonal_adjustment)
    "CPIAUCSL":     ("us.inflation.cpi_all",          "CPI All Urban Consumers",    "index",        "monthly",   "sa"),
    "CPILFESL":     ("us.inflation.cpi_core",          "Core CPI",                   "index",        "monthly",   "sa"),
    "PCEPILFE":     ("us.inflation.pce_core",          "Core PCE Price Index",        "index",        "monthly",   "sa"),
    "T5YIE":        ("us.inflation.breakeven_5y",      "5Y Breakeven Inflation",      "percent",      "daily",     "none"),
    "T10YIE":       ("us.inflation.breakeven_10y",     "10Y Breakeven Inflation",     "percent",      "daily",     "none"),
    "UNRATE":       ("us.employment.unemployment",     "Unemployment Rate",           "percent",      "monthly",   "sa"),
    "PAYEMS":       ("us.employment.nonfarm_payrolls", "Total Nonfarm Payrolls",      "thousands",    "monthly",   "sa"),
    "ICSA":         ("us.employment.initial_claims",   "Initial Jobless Claims",      "thousands",    "weekly",    "sa"),
    "CCSA":         ("us.employment.continuing_claims","Continuing Jobless Claims",   "thousands",    "weekly",    "sa"),
    "GDP":          ("us.growth.gdp_nominal",          "GDP",                         "billions_usd", "quarterly", "saar"),
    "GDPC1":        ("us.growth.gdp_real",             "Real GDP",                    "billions_usd", "quarterly", "saar"),
    "RSAFS":        ("us.growth.retail_sales",         "Retail Sales",                "millions_usd", "monthly",   "sa"),
    "INDPRO":       ("us.growth.industrial_production","Industrial Production",       "index",        "monthly",   "sa"),
    "DFF":          ("us.rates.fed_funds",             "Fed Funds Rate",              "percent",      "daily",     "none"),
    "DGS2":         ("us.rates.treasury_2y",           "2Y Treasury Yield",           "percent",      "daily",     "none"),
    "DGS10":        ("us.rates.treasury_10y",          "10Y Treasury Yield",          "percent",      "daily",     "none"),
    "DGS30":        ("us.rates.treasury_30y",          "30Y Treasury Yield",          "percent",      "daily",     "none"),
    "DFII10":       ("us.rates.real_yield_10y",        "10Y Real Yield",              "percent",      "daily",     "none"),
    "T10Y2Y":       ("us.rates.spread_10y2y",          "10Y-2Y Spread",               "percent",      "daily",     "none"),
    "WALCL":        ("us.liquidity.fed_balance_sheet", "Fed Balance Sheet",           "millions_usd", "weekly",    "none"),
    "M2SL":         ("us.liquidity.m2",                "M2 Money Supply",             "billions_usd", "monthly",   "sa"),
    "RRPONTSYD":    ("us.liquidity.reverse_repo",      "Reverse Repo",                "billions_usd", "daily",     "none"),
    "WTREGEN":      ("us.liquidity.tga",               "Treasury General Account",    "millions_usd", "weekly",    "none"),
    "DTWEXBGS":     ("us.fx.dollar_index_broad",       "Broad Dollar Index",          "index",        "daily",     "none"),
    "DEXCHUS":      ("us.fx.cny_usd",                  "CNY/USD Exchange Rate",       "ratio",        "daily",     "none"),
    "BAMLH0A0HYM2": ("us.credit.hy_oas",              "High Yield OAS",              "percent",      "daily",     "none"),
}

_EIA_FAMILY_MAP: dict[str, tuple[str, str, str, str, str]] = {
    # series_id: (family_id, canonical_name, unit, frequency, seasonal_adjustment)
    "EIA_BRENT":         ("us.energy.brent_spot",        "Brent Crude Spot Price",      "usd_per_barrel",           "daily",  "none"),
    "EIA_WTI":           ("us.energy.wti_spot",           "WTI Crude Spot Price",        "usd_per_barrel",           "daily",  "none"),
    "EIA_CRUDE_STOCKS":  ("us.energy.crude_stocks",       "Crude Oil Stocks",            "thousand_barrels",         "weekly", "none"),
    "EIA_NATGAS":        ("us.energy.natgas_futures",      "Natural Gas Futures",         "usd_per_mmbtu",           "daily",  "none"),
    "EIA_PETROL_SUPPLY": ("us.energy.petroleum_supply",    "Petroleum Supply",            "thousand_barrels_per_day", "weekly", "none"),
}

_TREASURY_FAMILY_MAP: dict[str, tuple[str, str, str, str, str]] = {
    # series_id: (family_id, canonical_name, unit, frequency, seasonal_adjustment)
    "TREAS_DEBT_TOTAL":  ("us.fiscal.debt_outstanding",   "Debt Outstanding",            "millions_usd", "daily",   "none"),
    "TREAS_TGA_BALANCE": ("us.fiscal.tga_balance",        "TGA Balance",                 "millions_usd", "daily",   "none"),
    "TREAS_AVG_RATE":    ("us.fiscal.avg_interest_rate",   "Average Interest Rate",       "percent",      "monthly", "none"),
}

_NYFED_FAMILY_MAP: dict[str, tuple[str, str, str, str, str]] = {
    # series_id: (family_id, canonical_name, unit, frequency, seasonal_adjustment)
    "NYFED_SOFR": ("us.rates.sofr", "Secured Overnight Financing Rate", "percent", "daily", "none"),
    "NYFED_EFFR": ("us.rates.effr", "Effective Federal Funds Rate",     "percent", "daily", "none"),
    "NYFED_OBFR": ("us.rates.obfr", "Overnight Bank Funding Rate",     "percent", "daily", "none"),
}

_IMF_FAMILY_MAP: dict[str, tuple[str, str, str, str, str]] = {
    # series_id: (family_id, canonical_name, unit, frequency, seasonal_adjustment)
    "IMF_CN_CPI":         ("cn.inflation.cpi",          "China CPI Index",              "index",        "monthly",    "none"),
    "IMF_CN_GDP":         ("cn.growth.gdp_real",         "China Real GDP (LCU)",         "lcu",          "quarterly",  "none"),
    "IMF_CN_FX_RESERVES": ("cn.reserves.fx",             "China FX Reserves (USD)",      "millions_usd", "monthly",    "none"),
    "IMF_JP_CPI":         ("jp.inflation.cpi",           "Japan CPI Index",              "index",        "monthly",    "none"),
    "IMF_JP_GDP":         ("jp.growth.gdp_real",          "Japan Real GDP (LCU)",         "lcu",          "quarterly",  "none"),
    "IMF_EU_CPI":         ("eu.inflation.cpi_imf",        "Euro Area CPI Index (IMF)",   "index",        "monthly",    "none"),
    "IMF_GLOBAL_TRADE":   ("us.trade.exports_fob",        "US Exports FOB (USD)",        "millions_usd", "monthly",    "none"),
}

_EUROSTAT_FAMILY_MAP: dict[str, tuple[str, str, str, str, str]] = {
    # series_id: (family_id, canonical_name, unit, frequency, seasonal_adjustment)
    "ESTAT_HICP":          ("eu.inflation.hicp",            "EA HICP YoY %",                     "percent",  "monthly",    "none"),
    "ESTAT_GDP":           ("eu.growth.gdp_qoq",            "EA GDP QoQ %",                      "percent",  "quarterly",  "sa"),
    "ESTAT_UNEMPLOYMENT":  ("eu.employment.unemployment",    "EA Unemployment Rate",              "percent",  "monthly",    "sa"),
    "ESTAT_INDPRO":        ("eu.growth.industrial_production", "EA Industrial Production MoM",    "percent",  "monthly",    "sa"),
    "ESTAT_ESI":           ("eu.sentiment.esi",              "EA Economic Sentiment Indicator",   "index",        "monthly", "sa"),
}

_BIS_FAMILY_MAP: dict[str, tuple[str, str, str, str, str]] = {
    # series_id: (family_id, canonical_name, unit, frequency, seasonal_adjustment)
    "BIS_POLICY_US": ("us.rates.policy_bis",     "US Policy Rate (BIS)",          "percent", "monthly",    "none"),
    "BIS_POLICY_EU": ("eu.rates.policy_bis",     "ECB Policy Rate (BIS)",         "percent", "monthly",    "none"),
    "BIS_POLICY_JP": ("jp.rates.policy_bis",     "BOJ Policy Rate (BIS)",         "percent", "monthly",    "none"),
    "BIS_POLICY_CN": ("cn.rates.policy_bis",     "PBOC Policy Rate (BIS)",        "percent", "monthly",    "none"),
    "BIS_POLICY_GB": ("gb.rates.policy_bis",     "BOE Policy Rate (BIS)",         "percent", "monthly",    "none"),
    "BIS_EER_US":    ("us.fx.eer_real",          "US Real Effective Exchange Rate",  "index", "monthly",    "none"),
    "BIS_EER_CN":    ("cn.fx.eer_real",          "CN Real Effective Exchange Rate",  "index", "monthly",    "none"),
    "BIS_EER_EU":    ("eu.fx.eer_real",          "EU Real Effective Exchange Rate",  "index", "monthly",    "none"),
    "BIS_CREDIT_GAP_US": ("us.credit.gap",       "US Credit-to-GDP Gap",           "percent", "quarterly", "none"),
    "BIS_CREDIT_GAP_CN": ("cn.credit.gap",       "CN Credit-to-GDP Gap",           "percent", "quarterly", "none"),
    "BIS_PROPERTY_US":   ("us.property.real",     "US Real Property Prices",        "index",   "quarterly", "none"),
    "BIS_PROPERTY_CN":   ("cn.property.real",     "CN Real Property Prices",        "index",   "quarterly", "none"),
}

_ECB_FAMILY_MAP: dict[str, tuple[str, str, str, str, str]] = {
    # series_id: (family_id, canonical_name, unit, frequency, seasonal_adjustment)
    "ECB_EA_M1":           ("eu.liquidity.m1",        "EA M1 Money Supply",        "millions_eur", "monthly", "sa"),
    "ECB_EA_M2":           ("eu.liquidity.m2",        "EA M2 Money Supply",        "millions_eur", "monthly", "sa"),
    "ECB_EA_M3":           ("eu.liquidity.m3",        "EA M3 Money Supply",        "millions_eur", "monthly", "sa"),
    "ECB_EA_M3_GROWTH":    ("eu.liquidity.m3_growth", "EA M3 Annual Growth Rate",  "percent",      "monthly", "none"),
    "ECB_EA_DEPOSIT_RATE": ("eu.rates.deposit_ecb",   "ECB Deposit Facility Rate", "percent",      "daily",   "none"),
    "ECB_EURUSD":          ("eu.fx.eurusd",           "EUR/USD Exchange Rate",     "ratio",        "monthly", "none"),
}

_OECD_FAMILY_MAP: dict[str, tuple[str, str, str, str, str]] = {
    # series_id: (family_id, canonical_name, unit, frequency, seasonal_adjustment)
    "OECD_CLI_US":           ("us.leading.cli",             "US Composite Leading Indicator",  "index",   "monthly", "none"),
    "OECD_CLI_CN":           ("cn.leading.cli",             "CN Composite Leading Indicator",  "index",   "monthly", "none"),
    "OECD_CLI_JP":           ("jp.leading.cli",             "JP Composite Leading Indicator",  "index",   "monthly", "none"),
    "OECD_CLI_EU":           ("eu.leading.cli",             "EA Composite Leading Indicator",  "index",   "monthly", "none"),
    "OECD_CONSUMER_CONF_US": ("us.sentiment.consumer_conf", "US Consumer Confidence (OECD)",   "index",   "monthly", "sa"),
    "OECD_BUSINESS_CONF_US": ("us.sentiment.business_conf", "US Business Confidence (OECD)",   "index",   "monthly", "sa"),
    "OECD_UNEMP_US":         ("us.employment.unemployment_oecd", "US Unemployment Rate (OECD)", "percent", "monthly", "sa"),
}

_WORLDBANK_FAMILY_MAP: dict[str, tuple[str, str, str, str, str]] = {
    # series_id: (family_id, canonical_name, unit, frequency, seasonal_adjustment)
    "WB_GDP_PCAP_US":   ("us.development.gdp_per_capita", "US GDP per Capita PPP",    "usd",     "annual", "none"),
    "WB_GDP_PCAP_CN":   ("cn.development.gdp_per_capita", "CN GDP per Capita PPP",    "usd",     "annual", "none"),
    "WB_GDP_GROWTH_US": ("us.growth.gdp_growth_wb",       "US GDP Growth % (WB)",     "percent", "annual", "none"),
    "WB_CA_GDP_US":     ("us.trade.current_account_gdp",   "US Current Account % GDP", "percent", "annual", "none"),
}

_VINTAGE_FAMILY_IDS = {"GDP", "GDPC1", "CPIAUCSL", "PAYEMS", "UNRATE", "INDPRO", "RSAFS", "IMF_CN_GDP", "IMF_JP_GDP"}

_OBS_DOC_LINKS: list[tuple[str, str, str]] = [
    ("us.inflation.cpi_all",           "us.bls.cpi",       "produced_by"),
    ("us.inflation.cpi_core",          "us.bls.cpi",       "produced_by"),
    ("us.inflation.pce_core",          "us.bea.pce",       "produced_by"),
    ("us.employment.nonfarm_payrolls", "us.bls.nfp",       "produced_by"),
    ("us.employment.unemployment",     "us.bls.nfp",       "produced_by"),
    ("us.growth.gdp_nominal",          "us.bea.gdp",       "produced_by"),
    ("us.growth.gdp_real",             "us.bea.gdp",       "produced_by"),
    ("us.growth.retail_sales",         "us.census.retail",  "produced_by"),
    ("us.growth.industrial_production","us.fed.ip",         "produced_by"),
    ("us.fiscal.debt_outstanding",     "us.treasury.debt",  "produced_by"),
    # Eurostat numeric ↔ Eurostat publications
    ("eu.inflation.hicp",             "eu.eurostat.cpi",        "produced_by"),
    ("eu.growth.gdp_qoq",            "eu.eurostat.gdp",        "produced_by"),
    ("eu.employment.unemployment",    "eu.eurostat.employment",  "produced_by"),
]

_OBS_SOURCE_DEFS: list[tuple[str, str, str, str, str, str, str]] = [
    # source_id, source_code, source_name, source_type, country_code, homepage_url, api_base_url
    ("fred",            "fred",            "Federal Reserve Economic Data",     "data_aggregator",   "US", "https://fred.stlouisfed.org",                                    "https://api.stlouisfed.org/fred"),
    ("eia",             "eia",             "Energy Information Administration", "government_agency", "US", "https://www.eia.gov",                                            "https://api.eia.gov/v2"),
    ("treasury_fiscal", "treasury_fiscal", "Treasury Fiscal Data",             "government_agency", "US", "https://fiscaldata.treasury.gov",                                "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"),
    ("nyfed",           "nyfed",           "Federal Reserve Bank of New York", "central_bank",      "US", "https://www.newyorkfed.org",                                     "https://markets.newyorkfed.org/api"),
    ("rateprobability", "rateprobability", "rateprobability.com",              "market_data",       "US", "https://rateprobability.com",                                    "https://rateprobability.com/api"),
    ("imf",             "imf",             "International Monetary Fund",      "data_aggregator",   "US", "https://www.imf.org",                                           "https://api.imf.org/external/sdmx/3.0"),
    ("eurostat",        "eurostat",        "Eurostat",                         "government_agency", "EU", "https://ec.europa.eu/eurostat",                                  "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"),
    ("bis",             "bis",             "Bank for International Settlements","data_aggregator",  "CH", "https://www.bis.org",                                           "https://stats.bis.org/api/v2"),
    ("ecb",             "ecb",             "European Central Bank",             "central_bank",     "EU", "https://www.ecb.europa.eu",                                      "https://data-api.ecb.europa.eu/service/data"),
    ("oecd",            "oecd",            "Organisation for Economic Co-operation", "data_aggregator", "XX", "https://www.oecd.org",                                      "https://sdmx.oecd.org/public/rest/v2"),
    ("worldbank",       "worldbank",       "World Bank",                        "data_aggregator",  "XX", "https://www.worldbank.org",                                      "https://api.worldbank.org/v2"),
]

# ── Calendar indicator seed data ──────────────────────────────────────

# (indicator_id, canonical_name, topic, country_code, frequency, unit, obs_family_id)
_CALENDAR_INDICATOR_DEFS: list[tuple[str, str, str, str, str, str, str]] = [
    # -- US Inflation --
    ("us.inflation.cpi_mom",      "CPI MoM",               "inflation",  "US", "monthly",   "percent", ""),
    ("us.inflation.cpi_yoy",      "CPI YoY",               "inflation",  "US", "monthly",   "percent", "us.inflation.cpi_all"),
    ("us.inflation.core_cpi_mom", "Core CPI MoM",          "inflation",  "US", "monthly",   "percent", ""),
    ("us.inflation.core_cpi_yoy", "Core CPI YoY",          "inflation",  "US", "monthly",   "percent", "us.inflation.cpi_core"),
    ("us.inflation.pce_mom",      "PCE Price Index MoM",   "inflation",  "US", "monthly",   "percent", ""),
    ("us.inflation.pce_yoy",      "PCE Price Index YoY",   "inflation",  "US", "monthly",   "percent", ""),
    ("us.inflation.core_pce_mom", "Core PCE MoM",          "inflation",  "US", "monthly",   "percent", ""),
    ("us.inflation.core_pce_yoy", "Core PCE YoY",          "inflation",  "US", "monthly",   "percent", "us.inflation.pce_core"),
    ("us.inflation.ppi_mom",      "PPI MoM",               "inflation",  "US", "monthly",   "percent", ""),
    ("us.inflation.ppi_yoy",      "PPI YoY",               "inflation",  "US", "monthly",   "percent", ""),
    # -- US Employment --
    ("us.employment.nfp",                "Nonfarm Payrolls",          "employment", "US", "monthly", "thousands", "us.employment.nonfarm_payrolls"),
    ("us.employment.unemployment_rate",  "Unemployment Rate",         "employment", "US", "monthly", "percent",   "us.employment.unemployment"),
    ("us.employment.initial_claims",     "Initial Jobless Claims",    "employment", "US", "weekly",  "thousands", "us.employment.initial_claims"),
    ("us.employment.continuing_claims",  "Continuing Jobless Claims", "employment", "US", "weekly",  "thousands", "us.employment.continuing_claims"),
    ("us.employment.adp",               "ADP Employment Change",     "employment", "US", "monthly", "thousands", ""),
    ("us.employment.jolts",             "JOLTS Job Openings",        "employment", "US", "monthly", "thousands", ""),
    ("us.employment.avg_hourly_earnings","Avg Hourly Earnings MoM",  "employment", "US", "monthly", "percent",   ""),
    # -- US Growth --
    ("us.growth.gdp_qoq",          "GDP QoQ",                  "growth", "US", "quarterly", "percent", "us.growth.gdp_real"),
    ("us.growth.retail_sales_mom",  "Retail Sales MoM",         "growth", "US", "monthly",   "percent", "us.growth.retail_sales"),
    ("us.growth.ism_mfg_pmi",      "ISM Manufacturing PMI",    "growth", "US", "monthly",   "index",   ""),
    ("us.growth.ism_services_pmi",  "ISM Services PMI",         "growth", "US", "monthly",   "index",   ""),
    ("us.growth.industrial_prod",   "Industrial Production MoM","growth", "US", "monthly",   "percent", "us.growth.industrial_production"),
    ("us.growth.durable_goods",     "Durable Goods Orders MoM", "growth", "US", "monthly",   "percent", ""),
    ("us.growth.sp_global_mfg_pmi", "S&P Global Mfg PMI",      "growth", "US", "monthly",   "index",   ""),
    # -- US Policy --
    ("us.policy.fed_rate",       "Fed Interest Rate Decision", "policy", "US", "irregular", "percent", "us.rates.fed_funds"),
    ("us.policy.fomc_minutes",   "FOMC Minutes",               "policy", "US", "irregular", "",        ""),
    ("us.policy.fomc_statement", "FOMC Statement",             "policy", "US", "irregular", "",        ""),
    ("us.policy.fed_chair_speech","Fed Chair Speech",           "policy", "US", "irregular", "",        ""),
    # -- US Housing --
    ("us.housing.existing_home_sales", "Existing Home Sales",  "housing", "US", "monthly", "millions", ""),
    ("us.housing.new_home_sales",      "New Home Sales",       "housing", "US", "monthly", "thousands",""),
    ("us.housing.building_permits",    "Building Permits",     "housing", "US", "monthly", "millions", ""),
    # -- US Consumer --
    ("us.consumer.michigan_sentiment",  "Michigan Consumer Sentiment", "consumer", "US", "monthly", "index", ""),
    ("us.consumer.cb_confidence",       "CB Consumer Confidence",      "consumer", "US", "monthly", "index", ""),
    # -- US Trade --
    ("us.trade.balance", "Trade Balance", "trade", "US", "monthly", "billions_usd", ""),
    # -- EU --
    ("eu.inflation.hicp_yoy",      "HICP YoY",              "inflation",  "EU", "monthly",   "percent", "eu.inflation.hicp"),
    ("eu.inflation.hicp_mom",      "HICP MoM",              "inflation",  "EU", "monthly",   "percent", ""),
    ("eu.inflation.core_hicp_yoy", "Core HICP YoY",         "inflation",  "EU", "monthly",   "percent", ""),
    ("eu.growth.gdp_qoq",         "GDP QoQ",                "growth",     "EU", "quarterly", "percent", "eu.growth.gdp_qoq"),
    ("eu.employment.unemployment", "Unemployment Rate",      "employment", "EU", "monthly",   "percent", "eu.employment.unemployment"),
    ("eu.policy.ecb_rate",         "ECB Interest Rate Decision","policy",  "EU", "irregular", "percent", ""),
    # -- JP --
    ("jp.policy.boj_rate", "BOJ Interest Rate Decision", "policy",    "JP", "irregular", "percent", ""),
    ("jp.inflation.cpi_yoy","CPI YoY",                   "inflation", "JP", "monthly",   "percent", "jp.inflation.cpi"),
    ("jp.growth.gdp_qoq",  "GDP QoQ",                    "growth",    "JP", "quarterly", "percent", ""),
    # -- UK --
    ("gb.policy.boe_rate", "BOE Interest Rate Decision", "policy",    "UK", "irregular", "percent", ""),
    ("gb.inflation.cpi_yoy","CPI YoY",                   "inflation", "UK", "monthly",   "percent", ""),
    ("gb.growth.gdp_qoq",  "GDP QoQ",                    "growth",    "UK", "quarterly", "percent", ""),
    # -- CN --
    ("cn.policy.pboc_rate", "PBOC Interest Rate Decision","policy",    "CN", "irregular", "percent", ""),
    ("cn.inflation.cpi_yoy","CPI YoY",                    "inflation", "CN", "monthly",   "percent", "cn.inflation.cpi"),
    ("cn.growth.gdp_yoy",  "GDP YoY",                     "growth",    "CN", "quarterly", "percent", ""),
    ("cn.growth.mfg_pmi",  "Manufacturing PMI",            "growth",    "CN", "monthly",   "index",   ""),
]

# (alias_original, indicator_id, source, country_code)
_CALENDAR_ALIAS_DEFS: list[tuple[str, str, str, str]] = [
    # ── US Inflation ─────────────────────────────────────────────
    ("CPI m/m",                        "us.inflation.cpi_mom",      "investing",         "US"),
    ("CPI (MoM)",                      "us.inflation.cpi_mom",      "investing",         "US"),
    ("Consumer Price Index m/m",       "us.inflation.cpi_mom",      "forexfactory",      "US"),
    ("Inflation Rate MoM",             "us.inflation.cpi_mom",      "tradingeconomics",  "US"),
    ("CPI y/y",                        "us.inflation.cpi_yoy",      "investing",         "US"),
    ("CPI (YoY)",                      "us.inflation.cpi_yoy",      "investing",         "US"),
    ("Consumer Price Index (YoY)",     "us.inflation.cpi_yoy",      "investing",         "US"),
    ("Inflation Rate YoY",             "us.inflation.cpi_yoy",      "tradingeconomics",  "US"),
    ("Core CPI m/m",                   "us.inflation.core_cpi_mom", "investing",         "US"),
    ("Core CPI (MoM)",                 "us.inflation.core_cpi_mom", "investing",         "US"),
    ("Core Consumer Price Index m/m",  "us.inflation.core_cpi_mom", "forexfactory",      "US"),
    ("Core Inflation Rate MoM",        "us.inflation.core_cpi_mom", "tradingeconomics",  "US"),
    ("Core CPI y/y",                   "us.inflation.core_cpi_yoy", "investing",         "US"),
    ("Core CPI (YoY)",                 "us.inflation.core_cpi_yoy", "investing",         "US"),
    ("Core Inflation Rate YoY",        "us.inflation.core_cpi_yoy", "tradingeconomics",  "US"),
    ("PCE Price Index m/m",            "us.inflation.pce_mom",      "investing",         "US"),
    ("PCE Prices (MoM)",               "us.inflation.pce_mom",      "investing",         "US"),
    ("Personal Spending m/m",          "us.inflation.pce_mom",      "forexfactory",      "US"),
    ("PCE Price Index MoM",            "us.inflation.pce_mom",      "tradingeconomics",  "US"),
    ("PCE Price Index y/y",            "us.inflation.pce_yoy",      "investing",         "US"),
    ("PCE Prices (YoY)",               "us.inflation.pce_yoy",      "investing",         "US"),
    ("PCE Price Index YoY",            "us.inflation.pce_yoy",      "tradingeconomics",  "US"),
    ("Core PCE Price Index m/m",       "us.inflation.core_pce_mom", "investing",         "US"),
    ("Core PCE Prices (MoM)",          "us.inflation.core_pce_mom", "investing",         "US"),
    ("Core PCE Price Index MoM",       "us.inflation.core_pce_mom", "tradingeconomics",  "US"),
    ("Core PCE Price Index y/y",       "us.inflation.core_pce_yoy", "investing",         "US"),
    ("Core PCE Prices (YoY)",          "us.inflation.core_pce_yoy", "investing",         "US"),
    ("Core PCE Price Index YoY",       "us.inflation.core_pce_yoy", "tradingeconomics",  "US"),
    ("PPI m/m",                        "us.inflation.ppi_mom",      "investing",         "US"),
    ("PPI (MoM)",                      "us.inflation.ppi_mom",      "investing",         "US"),
    ("Producer Price Index m/m",       "us.inflation.ppi_mom",      "forexfactory",      "US"),
    ("PPI MoM",                        "us.inflation.ppi_mom",      "tradingeconomics",  "US"),
    ("PPI y/y",                        "us.inflation.ppi_yoy",      "investing",         "US"),
    ("PPI (YoY)",                      "us.inflation.ppi_yoy",      "investing",         "US"),
    ("PPI YoY",                        "us.inflation.ppi_yoy",      "tradingeconomics",  "US"),
    # ── US Employment ────────────────────────────────────────────
    ("Non-Farm Employment Change",     "us.employment.nfp",                "investing",         "US"),
    ("Nonfarm Payrolls",               "us.employment.nfp",                "investing",         "US"),
    ("Non-Farm Payrolls",              "us.employment.nfp",                "forexfactory",      "US"),
    ("Non Farm Payrolls",              "us.employment.nfp",                "tradingeconomics",  "US"),
    ("Nonfarm Payrolls Change",        "us.employment.nfp",                "tradingeconomics",  "US"),
    ("Unemployment Rate",              "us.employment.unemployment_rate",  "investing",         "US"),
    ("Unemployment Rate",              "us.employment.unemployment_rate",  "forexfactory",      "US"),
    ("Unemployment Rate",              "us.employment.unemployment_rate",  "tradingeconomics",  "US"),
    ("Initial Jobless Claims",         "us.employment.initial_claims",     "investing",         "US"),
    ("Unemployment Claims",            "us.employment.initial_claims",     "forexfactory",      "US"),
    ("Initial Claims",                 "us.employment.initial_claims",     "tradingeconomics",  "US"),
    ("Continuing Jobless Claims",      "us.employment.continuing_claims",  "investing",         "US"),
    ("Continuing Claims",              "us.employment.continuing_claims",  "tradingeconomics",  "US"),
    ("ADP Non-Farm Employment Change", "us.employment.adp",               "investing",         "US"),
    ("ADP Nonfarm Employment Change",  "us.employment.adp",               "investing",         "US"),
    ("ADP Employment Change",          "us.employment.adp",               "forexfactory",      "US"),
    ("ADP Employment Change",          "us.employment.adp",               "tradingeconomics",  "US"),
    ("JOLTS Job Openings",             "us.employment.jolts",             "investing",         "US"),
    ("JOLTs Job Openings",             "us.employment.jolts",             "forexfactory",      "US"),
    ("Job Openings",                   "us.employment.jolts",             "tradingeconomics",  "US"),
    ("Average Hourly Earnings m/m",    "us.employment.avg_hourly_earnings","investing",         "US"),
    ("Average Hourly Earnings (MoM)",  "us.employment.avg_hourly_earnings","investing",         "US"),
    ("Average Hourly Earnings MoM",    "us.employment.avg_hourly_earnings","tradingeconomics",  "US"),
    # ── US Growth ────────────────────────────────────────────────
    ("GDP q/q",                        "us.growth.gdp_qoq",          "investing",         "US"),
    ("Advance GDP q/q",                "us.growth.gdp_qoq",          "investing",         "US"),
    ("GDP (QoQ)",                      "us.growth.gdp_qoq",          "investing",         "US"),
    ("Preliminary GDP q/q",            "us.growth.gdp_qoq",          "investing",         "US"),
    ("Final GDP q/q",                  "us.growth.gdp_qoq",          "investing",         "US"),
    ("GDP Growth Rate QoQ",            "us.growth.gdp_qoq",          "tradingeconomics",  "US"),
    ("Advance GDP",                    "us.growth.gdp_qoq",          "forexfactory",      "US"),
    ("Final GDP",                      "us.growth.gdp_qoq",          "forexfactory",      "US"),
    ("Prelim GDP",                     "us.growth.gdp_qoq",          "forexfactory",      "US"),
    ("Retail Sales m/m",               "us.growth.retail_sales_mom",  "investing",         "US"),
    ("Retail Sales (MoM)",             "us.growth.retail_sales_mom",  "investing",         "US"),
    ("Retail Sales MoM",               "us.growth.retail_sales_mom",  "tradingeconomics",  "US"),
    ("Core Retail Sales m/m",          "us.growth.retail_sales_mom",  "forexfactory",      "US"),
    ("ISM Manufacturing PMI",          "us.growth.ism_mfg_pmi",      "investing",         "US"),
    ("ISM Manufacturing PMI",          "us.growth.ism_mfg_pmi",      "forexfactory",      "US"),
    ("ISM Manufacturing PMI",          "us.growth.ism_mfg_pmi",      "tradingeconomics",  "US"),
    ("ISM Non-Manufacturing PMI",      "us.growth.ism_services_pmi",  "investing",         "US"),
    ("ISM Services PMI",               "us.growth.ism_services_pmi",  "investing",         "US"),
    ("ISM Services PMI",               "us.growth.ism_services_pmi",  "forexfactory",      "US"),
    ("ISM Services PMI",               "us.growth.ism_services_pmi",  "tradingeconomics",  "US"),
    ("Industrial Production m/m",      "us.growth.industrial_prod",   "investing",         "US"),
    ("Industrial Production (MoM)",    "us.growth.industrial_prod",   "investing",         "US"),
    ("Industrial Production MoM",      "us.growth.industrial_prod",   "tradingeconomics",  "US"),
    ("Durable Goods Orders m/m",       "us.growth.durable_goods",     "investing",         "US"),
    ("Core Durable Goods Orders m/m",  "us.growth.durable_goods",     "investing",         "US"),
    ("Durable Goods Orders MoM",       "us.growth.durable_goods",     "tradingeconomics",  "US"),
    ("S&P Global Manufacturing PMI",   "us.growth.sp_global_mfg_pmi", "investing",         "US"),
    ("Flash Manufacturing PMI",        "us.growth.sp_global_mfg_pmi", "investing",         "US"),
    ("S&P Global Manufacturing PMI",   "us.growth.sp_global_mfg_pmi", "tradingeconomics",  "US"),
    # ── US Policy ────────────────────────────────────────────────
    ("Fed Interest Rate Decision",     "us.policy.fed_rate",          "investing",         "US"),
    ("Federal Funds Rate",             "us.policy.fed_rate",          "investing",         "US"),
    ("Federal Funds Rate",             "us.policy.fed_rate",          "forexfactory",      "US"),
    ("Fed Interest Rate Decision",     "us.policy.fed_rate",          "tradingeconomics",  "US"),
    ("FOMC Minutes",                   "us.policy.fomc_minutes",      "investing",         "US"),
    ("FOMC Meeting Minutes",           "us.policy.fomc_minutes",      "investing",         "US"),
    ("FOMC Meeting Minutes",           "us.policy.fomc_minutes",      "forexfactory",      "US"),
    ("FOMC Minutes",                   "us.policy.fomc_minutes",      "tradingeconomics",  "US"),
    ("FOMC Statement",                 "us.policy.fomc_statement",    "investing",         "US"),
    ("FOMC Statement",                 "us.policy.fomc_statement",    "forexfactory",      "US"),
    ("FOMC Statement",                 "us.policy.fomc_statement",    "tradingeconomics",  "US"),
    ("Fed Chair Powell Speaks",        "us.policy.fed_chair_speech",  "investing",         "US"),
    ("FOMC Press Conference",          "us.policy.fed_chair_speech",  "investing",         "US"),
    ("FOMC Press Conference",          "us.policy.fed_chair_speech",  "forexfactory",      "US"),
    # ── US Housing ───────────────────────────────────────────────
    ("Existing Home Sales",            "us.housing.existing_home_sales","investing",        "US"),
    ("Existing Home Sales",            "us.housing.existing_home_sales","forexfactory",     "US"),
    ("Existing Home Sales",            "us.housing.existing_home_sales","tradingeconomics", "US"),
    ("New Home Sales",                 "us.housing.new_home_sales",     "investing",        "US"),
    ("New Home Sales",                 "us.housing.new_home_sales",     "forexfactory",     "US"),
    ("New Home Sales",                 "us.housing.new_home_sales",     "tradingeconomics", "US"),
    ("Building Permits",               "us.housing.building_permits",   "investing",        "US"),
    ("Building Permits",               "us.housing.building_permits",   "forexfactory",     "US"),
    ("Building Permits",               "us.housing.building_permits",   "tradingeconomics", "US"),
    # ── US Consumer ──────────────────────────────────────────────
    ("Michigan Consumer Sentiment",            "us.consumer.michigan_sentiment", "investing",        "US"),
    ("Revised UoM Consumer Sentiment",         "us.consumer.michigan_sentiment", "investing",        "US"),
    ("Prelim UoM Consumer Sentiment",          "us.consumer.michigan_sentiment", "investing",        "US"),
    ("University of Michigan Consumer Sentiment","us.consumer.michigan_sentiment","tradingeconomics","US"),
    ("CB Consumer Confidence",                  "us.consumer.cb_confidence",      "investing",        "US"),
    ("Consumer Confidence",                     "us.consumer.cb_confidence",      "forexfactory",     "US"),
    ("Consumer Confidence",                     "us.consumer.cb_confidence",      "tradingeconomics", "US"),
    # ── US Trade ─────────────────────────────────────────────────
    ("Trade Balance",                  "us.trade.balance",            "investing",         "US"),
    ("Trade Balance",                  "us.trade.balance",            "forexfactory",      "US"),
    ("Trade Balance",                  "us.trade.balance",            "tradingeconomics",  "US"),
    # ── EU ───────────────────────────────────────────────────────
    ("CPI y/y",                        "eu.inflation.hicp_yoy",      "investing",         "EU"),
    ("CPI (YoY)",                      "eu.inflation.hicp_yoy",      "investing",         "EU"),
    ("HICP YoY",                       "eu.inflation.hicp_yoy",      "tradingeconomics",  "EU"),
    ("Inflation Rate YoY",             "eu.inflation.hicp_yoy",      "tradingeconomics",  "EU"),
    ("CPI m/m",                        "eu.inflation.hicp_mom",      "investing",         "EU"),
    ("HICP MoM",                       "eu.inflation.hicp_mom",      "tradingeconomics",  "EU"),
    ("Core CPI y/y",                   "eu.inflation.core_hicp_yoy", "investing",         "EU"),
    ("Core CPI (YoY)",                 "eu.inflation.core_hicp_yoy", "investing",         "EU"),
    ("Core Inflation Rate YoY",        "eu.inflation.core_hicp_yoy", "tradingeconomics",  "EU"),
    ("GDP q/q",                        "eu.growth.gdp_qoq",         "investing",         "EU"),
    ("GDP (QoQ)",                      "eu.growth.gdp_qoq",         "investing",         "EU"),
    ("GDP Growth Rate QoQ",            "eu.growth.gdp_qoq",         "tradingeconomics",  "EU"),
    ("Unemployment Rate",              "eu.employment.unemployment", "investing",         "EU"),
    ("Unemployment Rate",              "eu.employment.unemployment", "tradingeconomics",  "EU"),
    ("ECB Interest Rate Decision",     "eu.policy.ecb_rate",         "investing",         "EU"),
    ("ECB Main Refinancing Rate",      "eu.policy.ecb_rate",         "investing",         "EU"),
    ("Minimum Bid Rate",               "eu.policy.ecb_rate",         "forexfactory",      "EU"),
    ("ECB Interest Rate Decision",     "eu.policy.ecb_rate",         "tradingeconomics",  "EU"),
    # ── JP ───────────────────────────────────────────────────────
    ("BOJ Interest Rate Decision",     "jp.policy.boj_rate",         "investing",         "JP"),
    ("BOJ Policy Rate",                "jp.policy.boj_rate",         "investing",         "JP"),
    ("Monetary Policy Statement",      "jp.policy.boj_rate",         "forexfactory",      "JP"),
    ("BOJ Interest Rate Decision",     "jp.policy.boj_rate",         "tradingeconomics",  "JP"),
    ("CPI y/y",                        "jp.inflation.cpi_yoy",       "investing",         "JP"),
    ("National Core CPI y/y",          "jp.inflation.cpi_yoy",       "investing",         "JP"),
    ("Inflation Rate YoY",             "jp.inflation.cpi_yoy",       "tradingeconomics",  "JP"),
    ("GDP q/q",                        "jp.growth.gdp_qoq",         "investing",         "JP"),
    ("GDP Growth Rate QoQ",            "jp.growth.gdp_qoq",         "tradingeconomics",  "JP"),
    # ── UK ───────────────────────────────────────────────────────
    ("BOE Interest Rate Decision",     "gb.policy.boe_rate",         "investing",         "UK"),
    ("Official Bank Rate",             "gb.policy.boe_rate",         "forexfactory",      "UK"),
    ("BOE Interest Rate Decision",     "gb.policy.boe_rate",         "tradingeconomics",  "UK"),
    ("CPI y/y",                        "gb.inflation.cpi_yoy",       "investing",         "UK"),
    ("Inflation Rate YoY",             "gb.inflation.cpi_yoy",       "tradingeconomics",  "UK"),
    ("GDP q/q",                        "gb.growth.gdp_qoq",         "investing",         "UK"),
    ("GDP Growth Rate QoQ",            "gb.growth.gdp_qoq",         "tradingeconomics",  "UK"),
    # ── CN ───────────────────────────────────────────────────────
    ("PBoC Interest Rate Decision",    "cn.policy.pboc_rate",        "investing",         "CN"),
    ("PBOC Interest Rate Decision",    "cn.policy.pboc_rate",        "tradingeconomics",  "CN"),
    ("Chinese CPI y/y",                "cn.inflation.cpi_yoy",       "investing",         "CN"),
    ("CPI y/y",                        "cn.inflation.cpi_yoy",       "investing",         "CN"),
    ("Inflation Rate YoY",             "cn.inflation.cpi_yoy",       "tradingeconomics",  "CN"),
    ("GDP y/y",                        "cn.growth.gdp_yoy",          "investing",         "CN"),
    ("Chinese GDP q/q",                "cn.growth.gdp_yoy",          "investing",         "CN"),
    ("GDP Growth Rate YoY",            "cn.growth.gdp_yoy",          "tradingeconomics",  "CN"),
    ("Manufacturing PMI",              "cn.growth.mfg_pmi",          "investing",         "CN"),
    ("NBS Manufacturing PMI",          "cn.growth.mfg_pmi",          "investing",         "CN"),
    ("Manufacturing PMI",              "cn.growth.mfg_pmi",          "tradingeconomics",  "CN"),
]


