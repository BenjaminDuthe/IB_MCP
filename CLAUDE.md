# CLAUDE.md - IB MCP Trading

## REGLE ABSOLUE : Wiki-First

**AVANT de lire du code source, TOUJOURS consulter le Wiki (9 pages) :**

```
wikijs_get_page(path="IB-MCP-Trading")                         # Index + sommaire
wikijs_get_page(path="IB-MCP-Trading/<page>")                  # Page specifique
wikijs_search_pages(query="IB-MCP-Trading <sujet>")            # Recherche
```

**INTERDIT** : Glob/Grep/Read pour "explorer" l'architecture. Utiliser UNIQUEMENT pour les fichiers a modifier.

---

## REGLE ABSOLUE : Vaultwarden comme coffre-fort unique

**Tous les secrets (mots de passe, tokens, API keys) sont centralises dans Vaultwarden** (organisation `SiteCraft`, `https://vault.sitecraft-it.com`).

- **JAMAIS de secrets en clair** dans CLAUDE.md, MEMORY.md ou le code
- **Avant chaque tache necessitant un secret** : le recuperer depuis Vaultwarden
- **Apres chaque creation/modification de secret** : mettre a jour l'item Vaultwarden dans la collection du projet
- **Les .env restent le mecanisme d'execution** — Vaultwarden est la source de verite

---

## Structure

```
IB_MCP/
├── api_gateway/       # IB Client Portal Gateway Java (port 5055)
├── mcp_server/        # MCP Server principal IB (port 5002)
├── mcp_market_data/   # Service market data yfinance (port 5003)
├── mcp_sentiment/     # Service sentiment 11 sources (port 5004)
│   └── tools/         # finnhub, alphavantage, reddit, stocktwits, fear_greed,
│                      # rss, yfinance_news, google_trends, earnings_proximity,
│                      # grok_x_sentiment (conditionnel F&G<30), combined
├── rss_collector/     # Financial intelligence pipeline OpenClaw (port 5020)
├── scoring_engine/    # Trading agent V4 multi-couches OpenClaw (port 5030)
│   ├── agents/        # 4 analystes Ollama 8B GPU (technical, fundamental, macro, sentiment)
│   ├── backtest/      # V3 strategies + V4 (regime, combos, smart exits, walk-forward)
│   ├── risk/          # Position sizing, sector limits, drawdown
│   └── feedback/      # Performance tracking, drift detection
├── workers/           # Cloudflare Workers (stocktwits-proxy)
├── scripts/           # Scripts utilitaires (backfill_history.py)
└── docker-compose.yml # Orchestration 6 services
```

## Dependances externes

- **Ollama** (LXC 106, 192.168.1.120:11434) : LLM llama3.1:8b-instruct-q4_K_M sur GPU Intel Arc B570 (41 tok/s)
- **InfluxDB** (LXC 110, 192.168.1.123:8086) : Metriques trading (database=trading), 218K data points, 86 tickers, 10 ans
- **MongoDB** (LXC 110, 192.168.1.123:27017) : Intelligence marche (rss_collector, 138 feeds)
- **OpenClaw** (LXC 112, 192.168.1.125:18789) : Decision maker Claude Sonnet, recoit 4-5 rapports analystes
- **Grok xAI** (api.x.ai) : Sentiment X/Twitter conditionnel (F&G < 30, US tickers only)

## Commandes

```bash
# Dev
docker compose up -d          # Demarrer tous les services
docker compose logs -f <svc>  # Logs d'un service
```

## Points critiques

- **FastMCP 2.10.3** : pinner `pydantic>=2.11,<2.12`
- **FastMCP ASGI mount** : `mcp_app = mcp.streamable_http_app()` + `app.mount("/mcp", mcp_app)`
- **mcp_server existant** : utilise `mcp.run()` donc path = `/mcp/` (pas `/mcp/mcp/`)
- **Ports** : gateway=5055, mcp=5002, market_data=5003, sentiment=5004, rss=5020, scoring=5030
- **verify=False** : toutes les routes mcp_server utilisent `verify=False` car IB Client Portal a un certificat auto-signe (documente dans `mcp_server/config.py`)
- **Scorer V4** : 9 signaux (6 individuels + 3 combos), regime VIX, RSI exit, backteste sur 78 tickers x 10 ans
- **Grok conditionnel** : appele depuis pipeline.py (pas combined.py) uniquement si F&G < 30 + ticker US, avec briefing complet
- **Sentiment 11 sources** : finnhub, alphavantage, reddit, stocktwits, rss, yfinance_news, google_trends, fear_greed, earnings, grok_x, combined
