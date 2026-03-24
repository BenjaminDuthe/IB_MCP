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
├── api_gateway/       # FastAPI gateway IB Auth (port 5055)
├── mcp_server/        # MCP Server principal IB (port 5002)
├── mcp_market_data/   # Service market data yfinance (port 5003)
├── mcp_news/          # Service news Finnhub+RSS (port 5005)
├── mcp_sentiment/     # Service sentiment Reddit/StockTwits (port 5004)
├── rss_collector/     # Financial intelligence pipeline (port 5020)
├── scoring_engine/    # Trading agent multi-couches + Ollama (port 5030)
│   ├── agents/        # 4 analystes (technical, fundamental, macro, sentiment)
│   ├── debate/        # Bull/Bear debate (3 rounds Ollama)
│   ├── risk/          # Position sizing, sector limits, drawdown
│   └── feedback/      # Performance tracking, drift detection
├── telegram_bot/      # Bot Telegram orchestrator (port 5010)
├── shared/            # Code partage entre services (db_schema.sql)
├── scripts/           # Scripts utilitaires
├── tests/             # Tests
├── reports/           # Rapports generes
├── docker-compose.yml # Orchestration 9 services
└── ENDPOINTS.md       # Documentation endpoints
```

## Dependances externes

- **Ollama** (LXC 106, 192.168.1.120:11434) : LLM llama3.2:3b pour scoring_engine
- **InfluxDB** (LXC 110, 192.168.1.123:8086) : Metriques trading (database=trading)
- **MongoDB** (LXC 110, 192.168.1.123:27017) : Intelligence marche (rss_collector)

## Commandes

```bash
# Dev
docker compose up -d          # Demarrer tous les services
docker compose logs -f <svc>  # Logs d'un service

# Tests
pytest tests/ -v

# Services individuels
cd mcp_server && uvicorn main:app --port 5002
cd api_gateway && uvicorn main:app --port 5055
```

## Points critiques

- **FastMCP 2.10.3** : pinner `pydantic>=2.11,<2.12`
- **FastMCP ASGI mount** : `mcp_app = mcp.streamable_http_app()` + `app.mount("/mcp", mcp_app)`
- **mcp_server existant** : utilise `mcp.run()` donc path = `/mcp/` (pas `/mcp/mcp/`)
- **Ports** : gateway=5055, mcp=5002, market_data=5003, sentiment=5004, news=5005, telegram=5010, rss=5020, scoring=5030
