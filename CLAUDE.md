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
├── mcp_sentiment/     # Service sentiment Reddit/StockTwits/Finnhub (port 5004)
├── rss_collector/     # Financial intelligence pipeline OpenClaw (port 5020)
├── scoring_engine/    # Trading agent multi-couches OpenClaw (port 5030)
│   ├── agents/        # 4 analystes (technical, fundamental, macro, sentiment)
│   ├── risk/          # Position sizing, sector limits, drawdown
│   └── feedback/      # Performance tracking, drift detection
├── workers/           # Cloudflare Workers (stocktwits-proxy)
├── scripts/           # Scripts utilitaires (backfill_history.py)
└── docker-compose.yml # Orchestration 6 services
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
```

## Points critiques

- **FastMCP 2.10.3** : pinner `pydantic>=2.11,<2.12`
- **FastMCP ASGI mount** : `mcp_app = mcp.streamable_http_app()` + `app.mount("/mcp", mcp_app)`
- **mcp_server existant** : utilise `mcp.run()` donc path = `/mcp/` (pas `/mcp/mcp/`)
- **Ports** : gateway=5055, mcp=5002, market_data=5003, sentiment=5004, rss=5020, scoring=5030
