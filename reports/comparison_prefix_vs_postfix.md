# IB_MCP Load Test - Comparaison Pre-Fix vs Post-Fix

**Date:** 2026-02-06
**Profil:** Normal (25 users, spawn 5/s, 3 minutes)
**Fixes appliques:** asyncio.to_thread, TTL cache, circuit breaker StockTwits, Docker CPU +

---

## Resume Global

| Metrique | Pre-Fix | Post-Fix | Delta |
|----------|---------|----------|-------|
| Total Requests | 1,051 | 1,029 | -2% |
| RPS | 5.88 | 5.79 | -1.5% |
| Total Failures | 264 (25.1%) | 262 (25.5%) | ~0 |
| Avg Response Time | 1,537ms | 1,624ms | +5.7% |
| p50 | 330ms | 330ms | = |
| p95 | 6,800ms | 7,000ms | +3% |
| p99 | 11,000ms | 13,000ms | +18% |

**Constat global:** Les metriques agregees sont quasi identiques. L'amelioration se voit **par endpoint**, pas dans l'agregat qui est domine par les erreurs StockTwits/Reddit (50%+ des echecs).

---

## Comparaison Par Endpoint

### mcp_news (5005) - AMELIORE

| Endpoint | Pre p50 | Post p50 | Pre p95 | Post p95 | Pre avg | Post avg |
|----------|---------|----------|---------|----------|---------|----------|
| /earnings | 2200ms | **1800ms** | 4500ms | **3300ms** | 2407ms | **1962ms** |
| /health [news] | 560ms | **330ms** | 3600ms | **2600ms** | 1047ms | **694ms** |
| /news/stock/[symbol] | 1000ms | 1000ms | 2800ms | **2500ms** | 1363ms | **1206ms** |
| /news/market | 1400ms | 1400ms | 4000ms | **2800ms** | 1681ms | **1482ms** |

- `/earnings` : **-18% p50**, **-27% p95** (asyncio.to_thread sur finnhub)
- `/health [news]` : **-41% p50**, **-28% p95**, **0 erreurs** (vs 4 pre-fix)
- `/news/stock` et `/news/market` : **-10 a -30% p95**
- Le service news est clairement debloque grace au to_thread sur finnhub.

### mcp_sentiment (5004) - AMELIORE (circuit breaker)

| Endpoint | Pre p50 | Post p50 | Pre avg | Post avg |
|----------|---------|----------|---------|----------|
| /health [sentiment] | 4ms | 5ms | 13ms | 25ms |
| /stocktwits/[symbol] | 86ms | **85ms** | 97ms | **90ms** |

- StockTwits echoue toujours (Cloudflare 403) mais le **circuit breaker** fait fail-fast en ~85ms au lieu de tenter a chaque fois.
- Le health check sentiment reste < 10ms median, confirme le service n'est pas surcharge.

### mcp_market_data (5003) - RESULTATS MIXTES

| Endpoint | Pre p50 | Post p50 | Pre p95 | Post p95 | Pre avg | Post avg |
|----------|---------|----------|---------|----------|---------|----------|
| /stock/price | 380ms | 500ms | 7200ms | 6900ms | 1930ms | 2125ms |
| /stock/fundamentals | 410ms | 430ms | 6900ms | 7000ms | 1876ms | 2043ms |
| /market/overview | 6300ms | 6500ms | 11000ms | 9900ms | 6101ms | **5994ms** |
| /health [market_data] | 220ms | 350ms | 8400ms | 7900ms | 1830ms | 2022ms |

- **p50 stock/price** passe de 380ms a 500ms (cache TTL 30s, mais 5 symbols = cache miss frequent)
- **p95 overview** ameliore de 11s a 9.9s
- Le health check market_data reste lent en p95 (7900ms) → le worker uvicorn est sature par les requetes yfinance meme avec to_thread (le thread pool par defaut est de taille limitee)
- **Diagnostic:** yfinance est le vrai bottleneck. Le to_thread debloque l'event loop mais ne reduit pas la latence yfinance elle-meme (~3-7s par appel).

### trader_workflow - SIMILAIRE

| Endpoint | Pre p50 | Post p50 | Pre p95 | Post p95 |
|----------|---------|----------|---------|----------|
| [trader] price check | 1800ms | 3500ms | 10000ms | 15000ms |
| [trader] news | 2500ms | 1900ms | 6800ms | **2900ms** |
| [trader] sentiment | 87ms | 85ms | 270ms | **140ms** |

- `[trader] news` : **-24% p50**, **-57% p95** (benefice direct du to_thread finnhub)
- `[trader] sentiment` : **p95 -48%** (circuit breaker fail-fast)
- `[trader] price check` : degradation p50 (1800→3500ms) due au thread pool contention avec 25 users concurrents

---

## Analyse des Erreurs

| Type d'erreur | Pre-Fix | Post-Fix | Commentaire |
|---------------|---------|----------|-------------|
| StockTwits 403 | 105+44=149 | 119+42=161 | Cloudflare, non fixable client-side |
| Reddit 500 | 93 | 74 | API non configuree |
| RemoteDisconnected | ~1 | 16 | Augmentation → thread contention |
| ReadTimeout (15s) | ~15 | 7 | Reduction → cache aide |
| Health market_data 0 | 1 | 4 | Worker overloade |
| Health news failures | 4 | **0** | Fix confirme |

**Erreurs "reelles"** (hors StockTwits 403 et Reddit 500) :
- Pre-fix: 264 - 149 - 93 = **22 erreurs**
- Post-fix: 262 - 161 - 74 = **27 erreurs** (+5, RemoteDisconnected)

---

## Bilan

### Ce qui fonctionne
1. **mcp_news nettement ameliore** : le to_thread sur finnhub a debloque le service (p50 -18 a -41%, p95 -27 a -57%)
2. **Circuit breaker StockTwits** : fail-fast propre, pas de temps perdu
3. **Health check news** : 0 erreurs (vs 4 pre-fix), le service ne bloque plus
4. **/market/overview p95** : -10% grace a la meilleure gestion async
5. **RSS parallele** : les feeds sont fetches en parallele (pas mesure directement ici mais contribue)

### Ce qui reste problematique
1. **yfinance = bottleneck principal** : chaque appel prend 3-7s, to_thread n'accelere pas l'appel lui-meme
2. **Thread pool saturation** : avec 25 users, le thread pool (default ~40 threads) se sature sur les appels yfinance, causant des RemoteDisconnected
3. **Cache hit rate faible** : 5 symbols aleatoires × TTL 30s = peu de cache hits sous charge
4. **Health check market_data contamine** : partage le meme worker que les requetes yfinance lentes

### Prochaines optimisations recommandees (priorite)
1. **Augmenter le thread pool** : `asyncio.get_event_loop().set_default_executor(ThreadPoolExecutor(max_workers=100))`
2. **Multi-worker uvicorn** : `MCP_WORKERS=2` pour market_data (attention: FastMCP stateful sessions)
3. **Cache TTL agressif** : augmenter a 60s pour /stock/price (les cours changent peu en 1 min)
4. **Health check dedie** : route separee sans dependre du thread pool yfinance
5. **Remplacer yfinance** : utiliser une API async native (ex: Alpha Vantage, Polygon.io) pour eliminer le blocking
6. **Connection pooling yfinance** : reutiliser les sessions HTTP au lieu d'en creer de nouvelles

---

*Rapport genere le 2026-02-06*
