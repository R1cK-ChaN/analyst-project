from __future__ import annotations

from .sources_shared import OECDSeriesConfig

FED_FEEDS = {
    "press_releases": {
        "url": "https://www.federalreserve.gov/feeds/press_all.xml",
        "content_type": "statement",
    },
    "speeches": {
        "url": "https://www.federalreserve.gov/feeds/speeches.xml",
        "content_type": "speech",
    },
    "testimony": {
        "url": "https://www.federalreserve.gov/feeds/testimony.xml",
        "content_type": "testimony",
    },
}


FED_SPEAKERS = [
    "Powell",
    "Waller",
    "Bowman",
    "Williams",
    "Barr",
    "Cook",
    "Jefferson",
    "Kugler",
    "Musalem",
    "Goolsbee",
    "Bostic",
    "Daly",
    "Collins",
    "Harker",
    "Kashkari",
    "Logan",
    "Barkin",
    "Hammack",
    "Schmid",
]


MACRO_SERIES = {
    "CPIAUCSL": {"name": "CPI All Urban", "category": "inflation", "freq": "monthly"},
    "CPILFESL": {"name": "Core CPI", "category": "inflation", "freq": "monthly"},
    "PCEPILFE": {"name": "Core PCE Price Index", "category": "inflation", "freq": "monthly"},
    "T5YIE": {"name": "5Y Breakeven Inflation", "category": "inflation", "freq": "daily"},
    "T10YIE": {"name": "10Y Breakeven Inflation", "category": "inflation", "freq": "daily"},
    "UNRATE": {"name": "Unemployment Rate", "category": "employment", "freq": "monthly"},
    "PAYEMS": {"name": "Total Nonfarm Payrolls", "category": "employment", "freq": "monthly"},
    "ICSA": {"name": "Initial Jobless Claims", "category": "employment", "freq": "weekly"},
    "CCSA": {"name": "Continuing Jobless Claims", "category": "employment", "freq": "weekly"},
    "GDP": {"name": "GDP", "category": "growth", "freq": "quarterly"},
    "GDPC1": {"name": "Real GDP", "category": "growth", "freq": "quarterly"},
    "RSAFS": {"name": "Retail Sales", "category": "growth", "freq": "monthly"},
    "INDPRO": {"name": "Industrial Production", "category": "growth", "freq": "monthly"},
    "DFF": {"name": "Fed Funds Rate", "category": "rates", "freq": "daily"},
    "DGS2": {"name": "2Y Treasury Yield", "category": "rates", "freq": "daily"},
    "DGS10": {"name": "10Y Treasury Yield", "category": "rates", "freq": "daily"},
    "DGS30": {"name": "30Y Treasury Yield", "category": "rates", "freq": "daily"},
    "DFII10": {"name": "10Y Real Yield", "category": "rates", "freq": "daily"},
    "T10Y2Y": {"name": "10Y-2Y Spread", "category": "rates", "freq": "daily"},
    "WALCL": {"name": "Fed Balance Sheet", "category": "liquidity", "freq": "weekly"},
    "M2SL": {"name": "M2 Money Supply", "category": "liquidity", "freq": "monthly"},
    "RRPONTSYD": {"name": "Reverse Repo", "category": "liquidity", "freq": "daily"},
    "WTREGEN": {"name": "Treasury General Account", "category": "liquidity", "freq": "weekly"},
    "DTWEXBGS": {"name": "Broad Dollar Index", "category": "fx", "freq": "daily"},
    "DEXCHUS": {"name": "CNY/USD Exchange Rate", "category": "fx", "freq": "daily"},
    "BAMLH0A0HYM2": {"name": "High Yield OAS", "category": "credit", "freq": "daily"},
}


MACRO_WATCHLIST = {
    "equity": {
        "^GSPC": "S&P 500",
        "^IXIC": "NASDAQ",
        "^DJI": "Dow Jones",
        "^VIX": "VIX",
    },
    "global_equity": {
        "^STOXX50E": "Euro Stoxx 50",
        "^N225": "Nikkei 225",
        "^HSI": "Hang Seng",
        "000001.SS": "Shanghai Composite",
    },
    "fx": {
        "DX-Y.NYB": "Dollar Index",
        "USDJPY=X": "USD/JPY",
        "USDCNY=X": "USD/CNY",
    },
    "bond": {
        "^TNX": "10Y Treasury Yield",
        "^TYX": "30Y Treasury Yield",
        "^FVX": "5Y Treasury Yield",
    },
    "commodity": {
        "GC=F": "Gold",
        "CL=F": "WTI Crude Oil",
        "HG=F": "Copper",
    },
    "crypto": {
        "BTC-USD": "Bitcoin",
        "ETH-USD": "Ethereum",
    },
}


VINTAGE_SERIES = ["GDP", "GDPC1", "CPIAUCSL", "PAYEMS", "UNRATE", "INDPRO", "RSAFS"]


EIA_SERIES = {
    "petroleum_brent": {
        "route": "petroleum/pri/spt/data",
        "params": {"data[]": "value", "facets[product][]": "EPCBRENT", "frequency": "daily"},
        "series_id": "EIA_BRENT",
        "category": "energy",
    },
    "petroleum_wti": {
        "route": "petroleum/pri/spt/data",
        "params": {"data[]": "value", "facets[product][]": "EPCWTI", "frequency": "daily"},
        "series_id": "EIA_WTI",
        "category": "energy",
    },
    "petroleum_stocks": {
        "route": "petroleum/stoc/wstk/data",
        "params": {"data[]": "value", "facets[product][]": "EPC0", "frequency": "weekly"},
        "series_id": "EIA_CRUDE_STOCKS",
        "category": "energy",
    },
    "natgas_futures": {
        "route": "natural-gas/pri/fut/data",
        "params": {"data[]": "value", "frequency": "daily"},
        "series_id": "EIA_NATGAS",
        "category": "energy",
    },
    "petroleum_supply": {
        "route": "petroleum/sum/snd/data",
        "params": {"data[]": "value", "frequency": "weekly"},
        "series_id": "EIA_PETROL_SUPPLY",
        "category": "energy",
    },
}


TREASURY_DATASETS = {
    "debt_outstanding": {
        "endpoint": "v2/accounting/od/debt_to_penny",
        "series_id": "TREAS_DEBT_TOTAL",
        "category": "fiscal",
    },
    "dts_operating_cash": {
        "endpoint": "v1/accounting/dts/deposits_withdrawals_operating_cash",
        "series_id": "TREAS_TGA_BALANCE",
        "category": "fiscal",
    },
    "avg_interest_rates": {
        "endpoint": "v2/accounting/od/avg_interest_rates",
        "series_id": "TREAS_AVG_RATE",
        "category": "fiscal",
    },
}


IMF_SERIES = {
    "cn_cpi": {
        "dataflow": "CPI", "version": "5.0.0", "key": "CHN.CPI._T.IX.M",
        "series_id": "IMF_CN_CPI", "category": "inflation",
    },
    "cn_gdp": {
        "dataflow": "QNEA", "version": "7.0.0", "key": "CHN.B1GQ.V.NSA.XDC.Q",
        "series_id": "IMF_CN_GDP", "category": "growth",
    },
    "cn_fx_reserves": {
        "dataflow": "IRFCL", "version": "11.0.0", "key": "CHN.IRFCLDT1_IRFCL54_USD",
        "series_id": "IMF_CN_FX_RESERVES", "category": "reserves",
    },
    "jp_cpi": {
        "dataflow": "CPI", "version": "5.0.0", "key": "JPN.CPI._T.IX.M",
        "series_id": "IMF_JP_CPI", "category": "inflation",
    },
    "jp_gdp": {
        "dataflow": "QNEA", "version": "7.0.0", "key": "JPN.B1GQ.V.SA.XDC.Q",
        "series_id": "IMF_JP_GDP", "category": "growth",
    },
    "eu_cpi": {
        "dataflow": "CPI", "version": "5.0.0", "key": "G163.HICP._T.IX.M",
        "series_id": "IMF_EU_CPI", "category": "inflation",
    },
    "global_trade": {
        "dataflow": "ITG", "version": "4.0.0", "key": "USA.XG.FOB_USD.M",
        "series_id": "IMF_GLOBAL_TRADE", "category": "trade",
    },
}


IMF_VINTAGE_SERIES = ["cn_gdp", "jp_gdp"]


EUROSTAT_SERIES = {
    "hicp": {
        "dataset": "prc_hicp_manr",
        "params": {"coicop": "CP00", "geo": "EA20"},
        "series_id": "ESTAT_HICP", "category": "inflation",
    },
    "gdp": {
        "dataset": "namq_10_gdp",
        "params": {"na_item": "B1GQ", "geo": "EA20", "unit": "CLV_PCH_PRE", "s_adj": "SCA"},
        "series_id": "ESTAT_GDP", "category": "growth",
    },
    "unemployment": {
        "dataset": "une_rt_m",
        "params": {"age": "TOTAL", "sex": "T", "geo": "EA20", "s_adj": "SA", "unit": "PC_ACT"},
        "series_id": "ESTAT_UNEMPLOYMENT", "category": "employment",
    },
    "indpro": {
        "dataset": "sts_inpr_m",
        "params": {"nace_r2": "B-D", "geo": "EA20", "s_adj": "SCA", "unit": "PCH_PRE"},
        "series_id": "ESTAT_INDPRO", "category": "growth",
    },
    "esi": {
        "dataset": "teibs010",
        "params": {"geo": "EA20", "indic": "BS-ESI-I", "s_adj": "SA"},
        "series_id": "ESTAT_ESI", "category": "sentiment",
    },
}


BIS_SERIES = {
    "policy_us": {"dataflow": "WS_CBPOL", "key": "M.US", "series_id": "BIS_POLICY_US", "category": "rates"},
    "policy_eu": {"dataflow": "WS_CBPOL", "key": "M.XM", "series_id": "BIS_POLICY_EU", "category": "rates"},
    "policy_jp": {"dataflow": "WS_CBPOL", "key": "M.JP", "series_id": "BIS_POLICY_JP", "category": "rates"},
    "policy_cn": {"dataflow": "WS_CBPOL", "key": "M.CN", "series_id": "BIS_POLICY_CN", "category": "rates"},
    "policy_gb": {"dataflow": "WS_CBPOL", "key": "M.GB", "series_id": "BIS_POLICY_GB", "category": "rates"},
    "eer_us":    {"dataflow": "WS_EER",    "key": "M.R.B.US", "series_id": "BIS_EER_US", "category": "fx"},
    "eer_cn":    {"dataflow": "WS_EER",    "key": "M.R.B.CN", "series_id": "BIS_EER_CN", "category": "fx"},
    "eer_eu":    {"dataflow": "WS_EER",    "key": "M.R.B.XM", "series_id": "BIS_EER_EU", "category": "fx"},
    "credit_gap_us": {"dataflow": "WS_CREDIT_GAP", "key": "Q.US.P", "series_id": "BIS_CREDIT_GAP_US", "category": "credit"},
    "credit_gap_cn": {"dataflow": "WS_CREDIT_GAP", "key": "Q.CN.P", "series_id": "BIS_CREDIT_GAP_CN", "category": "credit"},
    "property_us":   {"dataflow": "WS_SPP",  "key": "Q.US.R", "series_id": "BIS_PROPERTY_US", "category": "property"},
    "property_cn":   {"dataflow": "WS_SPP",  "key": "Q.CN.R", "series_id": "BIS_PROPERTY_CN", "category": "property"},
}


ECB_SERIES = {
    "m1":            {"dataflow": "BSI", "key": "M.U2.Y.V.M10.X.I.U2.2300.Z01.E", "series_id": "ECB_EA_M1",           "category": "liquidity"},
    "m2":            {"dataflow": "BSI", "key": "M.U2.Y.V.M20.X.I.U2.2300.Z01.E", "series_id": "ECB_EA_M2",           "category": "liquidity"},
    "m3":            {"dataflow": "BSI", "key": "M.U2.Y.V.M30.X.I.U2.2300.Z01.E", "series_id": "ECB_EA_M3",           "category": "liquidity"},
    "m3_growth":     {"dataflow": "BSI", "key": "M.U2.N.V.M30.X.I.U2.2300.Z01.A", "series_id": "ECB_EA_M3_GROWTH",     "category": "liquidity"},
    "deposit_rate":  {"dataflow": "FM",  "key": "B.U2.EUR.4F.KR.DFR.LEV",        "series_id": "ECB_EA_DEPOSIT_RATE",  "category": "rates"},
    "eurusd":        {"dataflow": "EXR", "key": "M.USD.EUR.SP00.A",              "series_id": "ECB_EURUSD",           "category": "fx"},
}


OECD_SERIES = {
    "cli_us": OECDSeriesConfig(
        dataflow="DSD_STES@DF_CLI",
        series_id="OECD_CLI_US",
        category="leading",
        filters={
            "REF_AREA": "USA",
            "FREQ": "M",
            "MEASURE": "LI",
            "UNIT_MEASURE": "IX",
            "ACTIVITY": "_Z",
            "ADJUSTMENT": "NOR",
            "TRANSFORMATION": "IX",
            "TIME_HORIZ": "_Z",
            "METHODOLOGY": "H",
        },
    ),
    "cli_cn": OECDSeriesConfig(
        dataflow="DSD_STES@DF_CLI",
        series_id="OECD_CLI_CN",
        category="leading",
        filters={
            "REF_AREA": "CHN",
            "FREQ": "M",
            "MEASURE": "LI",
            "UNIT_MEASURE": "IX",
            "ACTIVITY": "_Z",
            "ADJUSTMENT": "NOR",
            "TRANSFORMATION": "IX",
            "TIME_HORIZ": "_Z",
            "METHODOLOGY": "H",
        },
    ),
    "cli_jp": OECDSeriesConfig(
        dataflow="DSD_STES@DF_CLI",
        series_id="OECD_CLI_JP",
        category="leading",
        filters={
            "REF_AREA": "JPN",
            "FREQ": "M",
            "MEASURE": "LI",
            "UNIT_MEASURE": "IX",
            "ACTIVITY": "_Z",
            "ADJUSTMENT": "NOR",
            "TRANSFORMATION": "IX",
            "TIME_HORIZ": "_Z",
            "METHODOLOGY": "H",
        },
    ),
    "cli_eu": OECDSeriesConfig(
        dataflow="DSD_STES@DF_CLI",
        series_id="OECD_CLI_EU",
        category="leading",
        filters={
            "REF_AREA": "G4E",
            "FREQ": "M",
            "MEASURE": "LI",
            "UNIT_MEASURE": "IX",
            "ACTIVITY": "_Z",
            "ADJUSTMENT": "NOR",
            "TRANSFORMATION": "IX",
            "TIME_HORIZ": "_Z",
            "METHODOLOGY": "H",
        },
    ),
    "consumer_conf": OECDSeriesConfig(
        dataflow="DSD_STES@DF_CS",
        series_id="OECD_CONSUMER_CONF_US",
        category="sentiment",
        key="USA.M.CCICP.*.*.*.*.*.*",
    ),
    "business_conf": OECDSeriesConfig(
        dataflow="DSD_STES@DF_BTS",
        series_id="OECD_BUSINESS_CONF_US",
        category="sentiment",
        key="USA.M.BCICP.*.*.*.*.*.*",
    ),
    "unemployment_us": OECDSeriesConfig(
        dataflow="DSD_KEI@DF_KEI",
        series_id="OECD_UNEMP_US",
        category="employment",
        filters={
            "REF_AREA": "USA",
            "FREQ": "M",
            "MEASURE": "UNEMP",
            "UNIT_MEASURE": "PT_LF",
            "ACTIVITY": "_T",
            "ADJUSTMENT": "Y",
            "TRANSFORMATION": "_Z",
        },
    ),
}


WORLDBANK_SERIES = {
    "gdp_pcap_us":   {"indicator": "NY.GDP.PCAP.PP.CD",  "country": "USA", "series_id": "WB_GDP_PCAP_US",   "category": "development"},
    "gdp_pcap_cn":   {"indicator": "NY.GDP.PCAP.PP.CD",  "country": "CHN", "series_id": "WB_GDP_PCAP_CN",   "category": "development"},
    "gdp_growth_us": {"indicator": "NY.GDP.MKTP.KD.ZG",  "country": "USA", "series_id": "WB_GDP_GROWTH_US", "category": "growth"},
    "ca_gdp_us":     {"indicator": "BN.CAB.XOKA.GD.ZS",  "country": "USA", "series_id": "WB_CA_GDP_US",     "category": "trade"},
}


