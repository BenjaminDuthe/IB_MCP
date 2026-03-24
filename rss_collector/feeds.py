from rss_collector.models import FeedConfig

FEEDS: list[FeedConfig] = [
    # =============================================
    # US STOCK (16 feeds)
    # =============================================
    FeedConfig(name="Yahoo Finance US", url="https://feeds.finance.yahoo.com/rss/2.0/headline?region=US&lang=en-US", category="us_stock"),
    FeedConfig(name="Yahoo Finance Top", url="https://feeds.finance.yahoo.com/rss/2.0/headline?s=yhoo&region=US&lang=en-US", category="us_stock"),
    FeedConfig(name="CNBC Top News", url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", category="us_stock"),
    FeedConfig(name="CNBC Finance", url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664", category="us_stock"),
    FeedConfig(name="CNBC Investing", url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839069", category="us_stock"),
    FeedConfig(name="CNBC Earnings", url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=15839135", category="us_stock"),
    FeedConfig(name="MarketWatch Top Stories", url="https://feeds.marketwatch.com/marketwatch/topstories/", category="us_stock"),
    FeedConfig(name="MarketWatch Markets", url="https://feeds.marketwatch.com/marketwatch/marketpulse/", category="us_stock"),
    FeedConfig(name="MarketWatch Stocks", url="https://feeds.marketwatch.com/marketwatch/StockstoWatch/", category="us_stock"),
    FeedConfig(name="Reuters Business", url="https://feeds.content.dowjones.io/public/rss/RSSMarketsMain", category="us_stock"),
    FeedConfig(name="Seeking Alpha Market News", url="https://seekingalpha.com/market_currents.xml", category="us_stock"),
    FeedConfig(name="Seeking Alpha Wall St", url="https://seekingalpha.com/tag/wall-st-breakfast.xml", category="us_stock"),
    FeedConfig(name="Benzinga General", url="https://www.benzinga.com/feed", category="us_stock"),
    FeedConfig(name="Benzinga Analyst Ratings", url="https://www.benzinga.com/feed/analyst-ratings", category="us_stock"),
    FeedConfig(name="Motley Fool", url="https://www.fool.com/feeds/index", category="us_stock"),
    FeedConfig(name="Nasdaq News", url="https://www.nasdaq.com/feed/rssoutbound?category=Markets", category="us_stock"),

    # =============================================
    # FR / EU (13 feeds)
    # =============================================
    FeedConfig(name="Les Echos Bourse", url="https://syndication.lesechos.fr/rss/rss_bourse.xml", category="fr_eu", language="fr"),
    FeedConfig(name="Les Echos Finance", url="https://syndication.lesechos.fr/rss/rss_finance_marches.xml", category="fr_eu", language="fr"),
    FeedConfig(name="Les Echos Economie", url="https://syndication.lesechos.fr/rss/rss_economie_france.xml", category="fr_eu", language="fr"),
    FeedConfig(name="Les Echos Industrie", url="https://syndication.lesechos.fr/rss/rss_industrie_services.xml", category="fr_eu", language="fr"),
    FeedConfig(name="Les Echos Monde", url="https://syndication.lesechos.fr/rss/rss_monde.xml", category="fr_eu", language="fr"),
    FeedConfig(name="BFM Business", url="https://www.bfmtv.com/rss/economie/", category="fr_eu", language="fr"),
    FeedConfig(name="ABC Bourse Marches", url="https://www.abcbourse.com/rss/displaynewsrss", category="fr_eu", language="fr"),
    FeedConfig(name="ABC Bourse Analyses", url="https://www.abcbourse.com/rss/analysesrss", category="fr_eu", language="fr"),
    # EasyBourse: RSS fermé (404/500)
    FeedConfig(name="Investir Les Echos", url="https://investir.lesechos.fr/rss/rss_une.xml", category="fr_eu", language="fr"),
    # Boursorama: RSS fermé (404)
    FeedConfig(name="CNBC Europe", url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19794221", category="fr_eu"),
    FeedConfig(name="Zonebourse Actu", url="https://www.zonebourse.com/rss/", category="fr_eu", language="fr"),
    FeedConfig(name="Capital Bourse", url="https://www.capital.fr/entreprises-marches/rss", category="fr_eu", language="fr"),
    FeedConfig(name="La Tribune Economie", url="https://www.latribune.fr/rss/rubriques/economie.html", category="fr_eu", language="fr"),
    FeedConfig(name="Reuters Europe", url="https://www.reutersagency.com/feed/?best-regions=europe&post_type=best", category="fr_eu"),

    # =============================================
    # SEC & EARNINGS (8 feeds)
    # =============================================
    FeedConfig(name="SEC EDGAR Recent", url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=&dateb=&owner=include&count=40&search_text=&output=atom", category="sec_earnings"),
    # SEC EFTS: API bloquée (403) — conservé pour retry
    FeedConfig(name="Investing.com Earnings", url="https://www.investing.com/rss/earnings.rss", category="sec_earnings"),
    FeedConfig(name="Nasdaq Trader Alerts", url="https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts", category="sec_earnings"),
    FeedConfig(name="Nasdaq IPO Calendar", url="https://www.nasdaq.com/feed/rssoutbound?category=IPOs", category="sec_earnings"),

    # =============================================
    # CENTRAL BANKS (9 feeds)
    # =============================================
    FeedConfig(name="Fed Press Releases", url="https://www.federalreserve.gov/feeds/press_all.xml", category="central_banks"),
    FeedConfig(name="Fed Speeches", url="https://www.federalreserve.gov/feeds/speeches.xml", category="central_banks"),
    FeedConfig(name="Fed Monetary Policy", url="https://www.federalreserve.gov/feeds/press_monetary.xml", category="central_banks"),
    FeedConfig(name="Fed Banking", url="https://www.federalreserve.gov/feeds/press_bcreg.xml", category="central_banks"),
    FeedConfig(name="Fed Other", url="https://www.federalreserve.gov/feeds/press_other.xml", category="central_banks"),
    FeedConfig(name="Fed Staff Reports", url="https://www.newyorkfed.org/research/staff_reports/index.rss", category="central_banks"),
    FeedConfig(name="ECB Press", url="https://www.ecb.europa.eu/rss/press.html", category="central_banks"),
    FeedConfig(name="ECB Publications", url="https://www.ecb.europa.eu/rss/pub.html", category="central_banks"),
    # Banque de France: 403 (Cloudflare)

    # =============================================
    # COMMODITIES & FOREX (12 feeds)
    # =============================================
    FeedConfig(name="Investing.com Commodities", url="https://www.investing.com/rss/commodities.rss", category="commodities_forex"),
    FeedConfig(name="Investing.com Forex", url="https://www.investing.com/rss/forex.rss", category="commodities_forex"),
    FeedConfig(name="Investing.com Forex Analysis", url="https://www.investing.com/rss/forex_Technical.rss", category="commodities_forex"),
    FeedConfig(name="FXStreet News", url="https://www.fxstreet.com/rss/news", category="commodities_forex"),
    FeedConfig(name="FXStreet Analysis", url="https://www.fxstreet.com/rss/technical-analysis", category="commodities_forex"),
    # DailyFX: redirect cassé (301→0 entries)
    # DailyForex: RSS fermé (404)
    FeedConfig(name="OilPrice", url="https://oilprice.com/rss/main", category="commodities_forex"),
    FeedConfig(name="Commodity TV", url="https://commodity-tv.com/rss/", category="commodities_forex"),
    # Kitco: RSS fermé (404)

    # =============================================
    # CRYPTO (8 feeds)
    # =============================================
    FeedConfig(name="CoinDesk", url="https://www.coindesk.com/arc/outboundfeeds/rss/", category="crypto"),
    FeedConfig(name="CoinTelegraph Main", url="https://cointelegraph.com/rss", category="crypto"),
    FeedConfig(name="CoinTelegraph Bitcoin", url="https://cointelegraph.com/rss/tag/bitcoin", category="crypto"),
    FeedConfig(name="CoinTelegraph Ethereum", url="https://cointelegraph.com/rss/tag/ethereum", category="crypto"),
    FeedConfig(name="CoinTelegraph DeFi", url="https://cointelegraph.com/rss/tag/defi", category="crypto"),
    FeedConfig(name="CoinTelegraph Regulation", url="https://cointelegraph.com/rss/tag/regulation", category="crypto"),
    FeedConfig(name="Investing.com Crypto", url="https://www.investing.com/rss/crypto.rss", category="crypto"),
    FeedConfig(name="Bitcoin Magazine", url="https://bitcoinmagazine.com/feed", category="crypto"),

    # =============================================
    # MACRO (8 feeds)
    # =============================================
    # IMF: RSS valide mais format incompatible feedparser (0 entries)
    # World Bank: RSS fermé (404)
    FeedConfig(name="Investing.com Economy", url="https://www.investing.com/rss/economic_indicators.rss", category="macro"),
    # OECD: 403 (Cloudflare)
    # Economie.gouv.fr: RSS fermé (200 mais vide)
    # Eurostat: RSS fermé (404)

    # =============================================
    # SECTOR (12 feeds)
    # =============================================
    FeedConfig(name="TechCrunch", url="https://techcrunch.com/feed/", category="sector"),
    FeedConfig(name="TechCrunch Startups", url="https://techcrunch.com/category/startups/feed/", category="sector"),
    FeedConfig(name="CNBC Technology", url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910", category="sector"),
    FeedConfig(name="CNBC Health", url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000108", category="sector"),
    FeedConfig(name="CNBC Energy", url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19836768", category="sector"),
    FeedConfig(name="CNBC Real Estate", url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000115", category="sector"),
    FeedConfig(name="MarketWatch Tech", url="https://feeds.marketwatch.com/marketwatch/software/", category="sector"),
    FeedConfig(name="MarketWatch Healthcare", url="https://feeds.marketwatch.com/marketwatch/healthcare/", category="sector"),
    FeedConfig(name="MarketWatch Financial", url="https://feeds.marketwatch.com/marketwatch/financial/", category="sector"),
    FeedConfig(name="MarketWatch Energy", url="https://feeds.marketwatch.com/marketwatch/energy/", category="sector"),
    FeedConfig(name="OilPrice Alt Energy", url="https://oilprice.com/rss/alternative_energy", category="sector"),
    FeedConfig(name="Benzinga Cannabis", url="https://www.benzinga.com/feed/cannabis", category="sector"),

    # =============================================
    # ANALYSIS & OPINION (17 feeds)
    # =============================================
    FeedConfig(name="FT Home", url="https://www.ft.com/?format=rss", category="analysis_opinion"),
    FeedConfig(name="FT World", url="https://www.ft.com/world?format=rss", category="analysis_opinion"),
    FeedConfig(name="FT Companies", url="https://www.ft.com/companies?format=rss", category="analysis_opinion"),
    FeedConfig(name="FT Markets", url="https://www.ft.com/markets?format=rss", category="analysis_opinion"),
    FeedConfig(name="FT Opinion", url="https://www.ft.com/opinion?format=rss", category="analysis_opinion"),
    FeedConfig(name="WSJ Markets", url="https://feeds.content.dowjones.io/public/rss/RSSMarketsMain", category="analysis_opinion"),
    FeedConfig(name="WSJ Business", url="https://feeds.content.dowjones.io/public/rss/WSJcomUSBusiness", category="analysis_opinion"),
    FeedConfig(name="WSJ Opinion", url="https://feeds.content.dowjones.io/public/rss/RSSOpinion", category="analysis_opinion"),
    FeedConfig(name="WSJ Tech", url="https://feeds.content.dowjones.io/public/rss/RSSWSJD", category="analysis_opinion"),
    FeedConfig(name="WSJ Lifestyle", url="https://feeds.content.dowjones.io/public/rss/RSSLifestyle", category="analysis_opinion"),
    FeedConfig(name="Economist Finance", url="https://www.economist.com/finance-and-economics/rss.xml", category="analysis_opinion"),
    FeedConfig(name="Economist Business", url="https://www.economist.com/business/rss.xml", category="analysis_opinion"),
    FeedConfig(name="Economist Leaders", url="https://www.economist.com/leaders/rss.xml", category="analysis_opinion"),
    FeedConfig(name="Economist Briefing", url="https://www.economist.com/briefing/rss.xml", category="analysis_opinion"),
    FeedConfig(name="CNBC Commentary", url="https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100370673", category="analysis_opinion"),
    FeedConfig(name="Investing.com Opinion", url="https://www.investing.com/rss/market_overview_Opinion.rss", category="analysis_opinion"),
    FeedConfig(name="Investing.com Analysis", url="https://www.investing.com/rss/market_overview_Technical.rss", category="analysis_opinion"),
]

CATEGORIES = sorted(set(f.category for f in FEEDS))
