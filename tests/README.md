# Tests de Charge - IB_MCP

Tests de montee en charge pour les microservices MCP (market_data, sentiment, news).

## Fichiers

| Fichier | Description |
|---------|-------------|
| `locustfile.py` | Scenarios Locust : HealthCheck, MarketData, Sentiment, News, RealisticTrader |
| `load_config.py` | Configuration : seuils (p50/p95/p99), profils de test, regles d'anomalie |
| `analyze_results.py` | Analyseur de resultats CSV : detection d'anomalies, rapport markdown/JSON |

## Services cibles

| Service | Port | Endpoints testes |
|---------|------|-----------------|
| mcp_market_data | 5003 | /health, /stock/price, /stock/fundamentals, /market/overview |
| mcp_sentiment | 5004 | /health, /sentiment/stocktwits, /sentiment/reddit |
| mcp_news | 5005 | /health, /news/stock, /news/market, /earnings |

## Utilisation

### Pre-requis

```bash
pip install locust
```

### Profils de test

```bash
# Quick smoke test (5 users, 30s)
locust -f tests/locustfile.py --headless -u 5 -r 1 -t 30s --csv reports/quick

# Baseline (10 users, 1 min)
locust -f tests/locustfile.py --headless -u 10 -r 2 -t 1m --csv reports/baseline

# Normal (25 users, 3 min)
locust -f tests/locustfile.py --headless -u 25 -r 5 -t 3m --csv reports/normal

# Stress progressif (10 -> 50 -> 100 -> 200 users)
locust -f tests/locustfile.py --headless -u 10 -r 5 -t 2m --csv reports/stress_step1
locust -f tests/locustfile.py --headless -u 50 -r 10 -t 3m --csv reports/stress_step2
locust -f tests/locustfile.py --headless -u 100 -r 20 -t 3m --csv reports/stress_step3
locust -f tests/locustfile.py --headless -u 200 -r 25 -t 5m --csv reports/stress_step4
```

### Analyse des resultats

```bash
# Generer un rapport markdown
python tests/analyze_results.py reports/stress_step1 -p stress

# Generer un rapport JSON
python tests/analyze_results.py reports/stress_step1 -p stress --json
```

## Seuils de performance

| Metrique | OK | Warning | Critical |
|----------|-----|---------|----------|
| p50 | < 100ms | < 500ms | > 500ms |
| p95 | < 500ms | < 2000ms | > 2000ms |
| p99 | < 2000ms | < 5000ms | > 5000ms |
| Error rate | 0% | < 1% | > 1% |

## Notes

- Les rapports generes (`reports/`) sont exclus du git via `.gitignore`
- Les erreurs StockTwits 503 sont attendues (circuit breaker actif)
- Les erreurs Reddit 503 sont attendues si l'API PRAW n'est pas configuree
- Le endpoint `/market/overview` est naturellement lent (~5-8s sans cache)
