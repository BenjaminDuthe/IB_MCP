"""Configuration: 78 tickers, 6 exchanges, market hours, services."""

import os
from zoneinfo import ZoneInfo

# --- Market hours ---
TZ_CET = ZoneInfo("Europe/Paris")
TZ_ET = ZoneInfo("America/New_York")

# --- Service URLs ---
MARKET_DATA_URL = os.environ.get("MCP_MARKET_DATA_URL", "http://mcp_market_data:5003")
SENTIMENT_URL = os.environ.get("MCP_SENTIMENT_URL", "http://mcp_sentiment:5004")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://192.168.1.120:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")
INFLUXDB_URL = os.environ.get("INFLUXDB_URL", "http://192.168.1.123:8086")
INFLUXDB_DATABASE = os.environ.get("INFLUXDB_DATABASE", "trading")
INFLUXDB_USER = os.environ.get("INFLUXDB_USER", "trading_writer")
INFLUXDB_PASSWORD = os.environ.get("INFLUXDB_PASSWORD", "")

# --- Discord ---
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# --- Alert threshold ---
SIGNAL_SCORE_THRESHOLD = int(os.environ.get("SIGNAL_SCORE_THRESHOLD", "4"))

# --- Feature flags ---
AGENT_LAYERS_ENABLED = os.environ.get("AGENT_LAYERS_ENABLED", "true").lower() == "true"
RISK_SIZING_ENABLED = os.environ.get("RISK_SIZING_ENABLED", "true").lower() == "true"
FEEDBACK_ENABLED = os.environ.get("FEEDBACK_ENABLED", "true").lower() == "true"

# --- Risk management ---
PORTFOLIO_VALUE = float(os.environ.get("PORTFOLIO_VALUE", "50000"))
MAX_POSITION_RISK_PCT = float(os.environ.get("MAX_POSITION_RISK_PCT", "2.0"))
MAX_SECTOR_EXPOSURE_PCT = float(os.environ.get("MAX_SECTOR_EXPOSURE_PCT", "40.0"))
DRAWDOWN_REDUCE_THRESHOLD = float(os.environ.get("DRAWDOWN_REDUCE_THRESHOLD", "5.0"))

# --- Performance tracking ---
WIN_RATE_DRIFT_THRESHOLD = float(os.environ.get("WIN_RATE_DRIFT_THRESHOLD", "0.60"))

# ============================================================================
# TICKER DATABASE — 78 tickers across 6 exchanges
# ============================================================================

# Default watchlist params for tickers without custom thresholds
_DEFAULT = {"t5d_threshold": 2.5, "rsi_threshold": 55, "require_sma200": True}

# Full ticker registry: info + sector + description + watchlist params
# fmt: off
TICKERS = {
    # ======================== NASDAQ ========================
    "NVDA":    {"name": "NVIDIA",           "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "GPU, IA, data centers, gaming",                          "t5d": 4.0, "rsi": 50, "sma200": False},
    "MSFT":    {"name": "Microsoft",        "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "Cloud Azure, Office 365, Windows, Xbox",                 "t5d": 1.5, "rsi": 55, "sma200": True},
    "GOOGL":   {"name": "Alphabet (Google)","country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "Recherche, pub digitale, Cloud, YouTube, Waymo",         "t5d": 3.0, "rsi": 50, "sma200": True},
    "AMZN":    {"name": "Amazon",           "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "E-commerce, AWS cloud, Alexa, streaming",                "t5d": 1.0, "rsi": 45, "sma200": False},
    "META":    {"name": "Meta Platforms",   "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "Facebook, Instagram, WhatsApp, metavers",                "t5d": 1.0, "rsi": 50, "sma200": True},
    "AAPL":    {"name": "Apple",            "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "iPhone, Mac, services (App Store, Apple TV+)",            "t5d": 3.5, "rsi": 50, "sma200": True},
    "NFLX":    {"name": "Netflix",          "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "Streaming video, production de contenu original",         "t5d": 3.0, "rsi": 50, "sma200": True},
    "TSLA":    {"name": "Tesla",            "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "Vehicules electriques, batteries, energie solaire",       "t5d": 5.0, "rsi": 50, "sma200": False},
    "AMD":     {"name": "AMD",              "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "Processeurs CPU/GPU, serveurs, gaming",                  "t5d": 4.0, "rsi": 50, "sma200": False},
    "AVGO":    {"name": "Broadcom",         "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "Semi-conducteurs, infrastructure reseau, logiciels",      "t5d": 3.0, "rsi": 50, "sma200": True},
    "ADBE":    {"name": "Adobe",            "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "Creative Cloud, Photoshop, PDF, marketing digital",      },
    "INTC":    {"name": "Intel",            "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "Processeurs x86, fonderies, IA embarquee",               },
    "QCOM":    {"name": "Qualcomm",         "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "Puces mobiles Snapdragon, 5G, licences brevets",          },
    "CSCO":    {"name": "Cisco",            "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "Equipements reseau, cybersecurite, collaboration",        },
    "SHOP":    {"name": "Shopify",          "country": "🇺🇸", "exchange": "NASDAQ", "sector": "tech",       "desc": "Plateforme e-commerce SaaS pour marchands",               },
    "COST":    {"name": "Costco",           "country": "🇺🇸", "exchange": "NASDAQ", "sector": "consumer",   "desc": "Entrepots de gros, club membership, alimentaire",         "t5d": 1.5, "rsi": 55, "sma200": True},
    "SBUX":    {"name": "Starbucks",        "country": "🇺🇸", "exchange": "NASDAQ", "sector": "consumer",   "desc": "Chaine mondiale de cafes, boissons, restauration",        },
    # ======================== NYSE ========================
    "CRM":     {"name": "Salesforce",       "country": "🇺🇸", "exchange": "NYSE",   "sector": "tech",       "desc": "CRM cloud, automatisation ventes, IA Einstein",          "t5d": 2.0, "rsi": 55, "sma200": True},
    "ORCL":    {"name": "Oracle",           "country": "🇺🇸", "exchange": "NYSE",   "sector": "tech",       "desc": "Bases de donnees, cloud OCI, ERP, applications",          },
    "IBM":     {"name": "IBM",              "country": "🇺🇸", "exchange": "NYSE",   "sector": "tech",       "desc": "Cloud hybride, IA Watson, consulting, mainframes",        },
    "UNH":     {"name": "UnitedHealth",     "country": "🇺🇸", "exchange": "NYSE",   "sector": "healthcare", "desc": "Assurance sante, gestion soins (Optum)",                  "t5d": 2.0, "rsi": 55, "sma200": True},
    "JNJ":     {"name": "Johnson & Johnson","country": "🇺🇸", "exchange": "NYSE",   "sector": "healthcare", "desc": "Pharma, dispositifs medicaux, sante grand public",        "t5d": 1.5, "rsi": 60, "sma200": True},
    "LLY":     {"name": "Eli Lilly",        "country": "🇺🇸", "exchange": "NYSE",   "sector": "healthcare", "desc": "Pharma (diabete, oncologie, Alzheimer, obesite)",         "t5d": 3.0, "rsi": 50, "sma200": True},
    "ABBV":    {"name": "AbbVie",           "country": "🇺🇸", "exchange": "NYSE",   "sector": "healthcare", "desc": "Pharma (immunologie Humira, oncologie, esthetique)",       },
    "PFE":     {"name": "Pfizer",           "country": "🇺🇸", "exchange": "NYSE",   "sector": "healthcare", "desc": "Pharma (vaccins, oncologie, anti-infectieux)",             },
    "MRK":     {"name": "Merck",            "country": "🇺🇸", "exchange": "NYSE",   "sector": "healthcare", "desc": "Pharma (oncologie Keytruda, vaccins, sante animale)",      },
    "TMO":     {"name": "Thermo Fisher",    "country": "🇺🇸", "exchange": "NYSE",   "sector": "healthcare", "desc": "Instruments scientifiques, diagnostics, biotech",          },
    "JPM":     {"name": "JPMorgan Chase",   "country": "🇺🇸", "exchange": "NYSE",   "sector": "finance",    "desc": "Banque universelle, investment banking, asset mgmt",       "t5d": 2.0, "rsi": 55, "sma200": True},
    "V":       {"name": "Visa",             "country": "🇺🇸", "exchange": "NYSE",   "sector": "finance",    "desc": "Reseau de paiement mondial, cartes, fintech",             "t5d": 1.5, "rsi": 55, "sma200": True},
    "GS":      {"name": "Goldman Sachs",    "country": "🇺🇸", "exchange": "NYSE",   "sector": "finance",    "desc": "Investment banking, trading, asset management",            },
    "BAC":     {"name": "Bank of America",  "country": "🇺🇸", "exchange": "NYSE",   "sector": "finance",    "desc": "Banque retail, wealth management, trading",                },
    "MA":      {"name": "Mastercard",       "country": "🇺🇸", "exchange": "NYSE",   "sector": "finance",    "desc": "Reseau de paiement mondial, cybersecurite paiements",      },
    "BLK":     {"name": "BlackRock",        "country": "🇺🇸", "exchange": "NYSE",   "sector": "finance",    "desc": "Gestion d'actifs #1 mondial, iShares ETF, Aladdin",        },
    "XOM":     {"name": "ExxonMobil",       "country": "🇺🇸", "exchange": "NYSE",   "sector": "energy",     "desc": "Petrole, gaz naturel, raffinage, chimie",                 "t5d": 3.0, "rsi": 55, "sma200": False},
    "CVX":     {"name": "Chevron",          "country": "🇺🇸", "exchange": "NYSE",   "sector": "energy",     "desc": "Petrole, gaz, LNG, energies renouvelables",               },
    "CAT":     {"name": "Caterpillar",      "country": "🇺🇸", "exchange": "NYSE",   "sector": "industrials","desc": "Engins BTP, mines, moteurs, equipements lourds",           "t5d": 2.5, "rsi": 55, "sma200": True},
    "BA":      {"name": "Boeing",           "country": "🇺🇸", "exchange": "NYSE",   "sector": "aerospace",  "desc": "Avions commerciaux, defense, espace",                     "t5d": 4.0, "rsi": 50, "sma200": False},
    "GE":      {"name": "GE Aerospace",     "country": "🇺🇸", "exchange": "NYSE",   "sector": "aerospace",  "desc": "Moteurs d'avion, maintenance aeronautique",               },
    "LMT":     {"name": "Lockheed Martin",  "country": "🇺🇸", "exchange": "NYSE",   "sector": "aerospace",  "desc": "Defense (F-35, missiles, espace, cyber)",                 },
    "RTX":     {"name": "RTX (Raytheon)",   "country": "🇺🇸", "exchange": "NYSE",   "sector": "aerospace",  "desc": "Defense (Pratt&Whitney, missiles, radars)",                },
    "DE":      {"name": "John Deere",       "country": "🇺🇸", "exchange": "NYSE",   "sector": "industrials","desc": "Machines agricoles, forestieres, BTP",                     },
    "UPS":     {"name": "UPS",              "country": "🇺🇸", "exchange": "NYSE",   "sector": "industrials","desc": "Livraison colis, logistique, supply chain",                },
    "HD":      {"name": "Home Depot",       "country": "🇺🇸", "exchange": "NYSE",   "sector": "consumer",   "desc": "Magasins bricolage/amenagement, B2B pro",                 "t5d": 2.0, "rsi": 55, "sma200": True},
    "WMT":     {"name": "Walmart",          "country": "🇺🇸", "exchange": "NYSE",   "sector": "consumer",   "desc": "Distribution #1 mondial, e-commerce, Sam's Club",         },
    "PG":      {"name": "Procter & Gamble", "country": "🇺🇸", "exchange": "NYSE",   "sector": "consumer",   "desc": "Hygiene, lessive, beaute (Pampers, Gillette, Oral-B)",    },
    "KO":      {"name": "Coca-Cola",        "country": "🇺🇸", "exchange": "NYSE",   "sector": "consumer",   "desc": "Boissons (Coca, Fanta, Sprite, Minute Maid)",             },
    "MCD":     {"name": "McDonald's",       "country": "🇺🇸", "exchange": "NYSE",   "sector": "consumer",   "desc": "Restauration rapide, franchise mondiale",                 },
    "NKE":     {"name": "Nike",             "country": "🇺🇸", "exchange": "NYSE",   "sector": "consumer",   "desc": "Chaussures, vetements sportifs, Jordan, Converse",        },
    "DIS":     {"name": "Disney",           "country": "🇺🇸", "exchange": "NYSE",   "sector": "consumer",   "desc": "Parcs, streaming Disney+, studios (Marvel, Pixar, Star Wars)", },
    # ======================== EURONEXT PARIS ========================
    "MC.PA":   {"name": "LVMH",              "country": "🇫🇷", "exchange": "Paris",  "sector": "luxury",     "desc": "Luxe (Louis Vuitton, Dior, Hennessy, Sephora)",           "t5d": 3.5, "rsi": 60, "sma200": False},
    "SU.PA":   {"name": "Schneider Electric","country": "🇫🇷", "exchange": "Paris",  "sector": "industrials","desc": "Gestion energie, automatisation industrielle, IoT",        "t5d": 4.0, "rsi": 55, "sma200": True},
    "AIR.PA":  {"name": "Airbus",            "country": "🇫🇷", "exchange": "Paris",  "sector": "aerospace",  "desc": "Avions commerciaux A320/A350, helicopteres, espace",      "t5d": 3.5, "rsi": 65, "sma200": False},
    "BNP.PA":  {"name": "BNP Paribas",       "country": "🇫🇷", "exchange": "Paris",  "sector": "finance",    "desc": "Banque universelle (retail, corporate, asset mgmt)",       "t5d": 2.5, "rsi": 50, "sma200": False},
    "SAF.PA":  {"name": "Safran",            "country": "🇫🇷", "exchange": "Paris",  "sector": "aerospace",  "desc": "Moteurs d'avion LEAP, equipements, defense",              "t5d": 2.0, "rsi": 50, "sma200": True},
    "TTE.PA":  {"name": "TotalEnergies",     "country": "🇫🇷", "exchange": "Paris",  "sector": "energy",     "desc": "Petrole, gaz, electricite, renouvelables",                "t5d": 3.5, "rsi": 55, "sma200": False},
    "OR.PA":   {"name": "L'Oréal",           "country": "🇫🇷", "exchange": "Paris",  "sector": "consumer",   "desc": "Cosmetiques #1 mondial (Lancome, Garnier, Maybelline)",   "t5d": 2.0, "rsi": 55, "sma200": True},
    "AI.PA":   {"name": "Air Liquide",       "country": "🇫🇷", "exchange": "Paris",  "sector": "materials",  "desc": "Gaz industriels, medicaux, hydrogene",                    },
    "DG.PA":   {"name": "Vinci",             "country": "🇫🇷", "exchange": "Paris",  "sector": "industrials","desc": "Concessions (autoroutes, aeroports), BTP, energie",        },
    "KER.PA":  {"name": "Kering",            "country": "🇫🇷", "exchange": "Paris",  "sector": "luxury",     "desc": "Luxe (Gucci, Saint Laurent, Bottega Veneta, Balenciaga)", },
    "SAN.PA":  {"name": "Sanofi",            "country": "🇫🇷", "exchange": "Paris",  "sector": "healthcare", "desc": "Pharma (Dupixent, vaccins, maladies rares)",               },
    "EL.PA":   {"name": "EssilorLuxottica",  "country": "🇫🇷", "exchange": "Paris",  "sector": "healthcare", "desc": "Verres optiques, lunettes (Ray-Ban, Oakley)",              },
    # ======================== XETRA FRANKFURT ========================
    "SAP.DE":  {"name": "SAP",               "country": "🇩🇪", "exchange": "Frankfurt","sector": "tech",     "desc": "ERP, cloud business, gestion d'entreprise",               "t5d": 2.0, "rsi": 55, "sma200": True},
    "SIE.DE":  {"name": "Siemens",           "country": "🇩🇪", "exchange": "Frankfurt","sector": "industrials","desc": "Automatisation, trains, infrastructure, sante",           "t5d": 2.5, "rsi": 55, "sma200": True},
    "DTE.DE":  {"name": "Deutsche Telekom",  "country": "🇩🇪", "exchange": "Frankfurt","sector": "telecom",   "desc": "Telecoms (T-Mobile US), fibre, 5G",                      },
    "ALV.DE":  {"name": "Allianz",           "country": "🇩🇪", "exchange": "Frankfurt","sector": "finance",   "desc": "Assurance, asset management (PIMCO)",                     },
    "BAS.DE":  {"name": "BASF",              "country": "🇩🇪", "exchange": "Frankfurt","sector": "materials", "desc": "Chimie #1 mondial, materiaux, agriculture",                },
    "ADS.DE":  {"name": "Adidas",            "country": "🇩🇪", "exchange": "Frankfurt","sector": "consumer",  "desc": "Chaussures et vetements sportifs",                        },
    "MUV2.DE": {"name": "Munich Re",         "country": "🇩🇪", "exchange": "Frankfurt","sector": "finance",   "desc": "Reassurance #1 mondial, gestion des risques",             },
    # ======================== EURONEXT AMSTERDAM ========================
    "ASML.AS": {"name": "ASML Holding",      "country": "🇳🇱", "exchange": "Amsterdam","sector": "tech",     "desc": "Machines lithographie EUV pour semi-conducteurs",          "t5d": 3.5, "rsi": 50, "sma200": True},
    "PHIA.AS": {"name": "Philips",           "country": "🇳🇱", "exchange": "Amsterdam","sector": "healthcare","desc": "Imagerie medicale, monitoring, sante connectee",           },
    "INGA.AS": {"name": "ING Group",         "country": "🇳🇱", "exchange": "Amsterdam","sector": "finance",   "desc": "Banque digitale, retail banking, wholesale",              },
    "AD.AS":   {"name": "Ahold Delhaize",    "country": "🇳🇱", "exchange": "Amsterdam","sector": "consumer",  "desc": "Distribution alimentaire (Albert Heijn, Delhaize, US)",   },
    # ======================== SIX ZURICH ========================
    "NESN.SW": {"name": "Nestlé",            "country": "🇨🇭", "exchange": "Zurich",  "sector": "consumer",  "desc": "Alimentaire #1 mondial (Nespresso, KitKat, Purina)",      },
    "NOVN.SW": {"name": "Novartis",          "country": "🇨🇭", "exchange": "Zurich",  "sector": "healthcare","desc": "Pharma (cardiologie, oncologie, immunologie, generiques)", },
    "ROG.SW":  {"name": "Roche",             "country": "🇨🇭", "exchange": "Zurich",  "sector": "healthcare","desc": "Pharma (oncologie, diagnostics, anticorps monoclonaux)",   },
    # ======================== LSE LONDON ========================
    "SHEL.L":  {"name": "Shell",             "country": "🇬🇧", "exchange": "London",  "sector": "energy",    "desc": "Petrole, gaz, LNG, transition energetique",               },
    "AZN.L":   {"name": "AstraZeneca",       "country": "🇬🇧", "exchange": "London",  "sector": "healthcare","desc": "Pharma (oncologie, respiratoire, vaccins, rare diseases)", },
    "HSBA.L":  {"name": "HSBC",              "country": "🇬🇧", "exchange": "London",  "sector": "finance",   "desc": "Banque mondiale, Asie-Pacifique, trade finance",          },
}
# fmt: on

# --- Derived lookups ---

TICKER_INFO = {t: {"name": d["name"], "country": d["country"], "exchange": d["exchange"]} for t, d in TICKERS.items()}
TICKER_SECTORS = {t: d["sector"] for t, d in TICKERS.items()}
TICKER_DESCRIPTION = {t: d.get("desc", "") for t, d in TICKERS.items()}

WATCHLIST = {
    t: {
        "market": d["exchange"],
        "t5d_threshold": d.get("t5d", _DEFAULT["t5d_threshold"]),
        "rsi_threshold": d.get("rsi", _DEFAULT["rsi_threshold"]),
        "require_sma200": d.get("sma200", _DEFAULT["require_sma200"]),
    }
    for t, d in TICKERS.items()
}

EXCHANGE_GROUPS = {}
for t, d in TICKERS.items():
    ex = d["exchange"]
    EXCHANGE_GROUPS.setdefault(ex, []).append(t)
