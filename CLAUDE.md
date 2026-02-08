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
├── api_gateway/       # FastAPI gateway (port 5055)
├── mcp_server/        # MCP Server principal IB (port 5002)
├── mcp_market_data/   # Service market data (port 5003)
├── mcp_news/          # Service news (port 5005)
├── mcp_sentiment/     # Service sentiment (port 5004)
├── telegram_bot/      # Bot Telegram (port 5010)
├── shared/            # Code partage entre services
├── scripts/           # Scripts utilitaires
├── tests/             # Tests
├── reports/           # Rapports generes
├── docker-compose.yml # Orchestration multi-services
└── ENDPOINTS.md       # Documentation endpoints
```

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
- **Ports** : gateway=5055, mcp=5002, market_data=5003, sentiment=5004, news=5005, telegram=5010
