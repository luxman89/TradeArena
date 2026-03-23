# TradeArena Load Testing Suite

Performance benchmarks and load tests for the TradeArena API.

## Quick Start

```bash
# Run pytest benchmarks (no server needed — uses TestClient)
uv run pytest loadtests/test_benchmarks.py -v -s

# Run locust load tests against a live server
uv run python loadtests/seed.py          # seed test data
uv run locust -f loadtests/locustfile.py --host http://localhost:8000

# Headless mode (CI-friendly)
uv run locust -f loadtests/locustfile.py --headless \
    -u 50 -r 10 --run-time 60s \
    --host http://localhost:8000
```

## Test Scenarios

| Scenario | Tool | What it measures |
|----------|------|------------------|
| Signal submissions | locust + pytest | Latency, throughput, rate-limit behavior |
| Leaderboard queries | locust + pytest | Read latency, cursor pagination, concurrent reads |
| WebSocket connections | locust | Connect time, message receive, ping/pong |
| Battle operations | locust + pytest | Create/resolve contention, history queries |

## Performance Thresholds

These are the baseline thresholds. Tests fail if p95 latency exceeds these values.

| Endpoint | p95 Threshold | Notes |
|----------|--------------|-------|
| `POST /signal` | 500ms | Includes DB write + score increment |
| `GET /leaderboard` | 200ms | With JOIN on scores table |
| `GET /leaderboard/{division}` | 200ms | Filtered variant |
| `POST /battle/create` | 300ms | Includes duplicate check |
| `GET /battles/active` | 150ms | Simple filtered query |
| `GET /battles/history` | 200ms | With pagination |
| `GET /health` | 50ms | Baseline overhead |
| 20 concurrent signals | 10s total | Across different creators |
| 50 concurrent leaderboard reads | 5s total | Mixed pagination |

## Architecture

```
loadtests/
├── common.py           # Shared config, payload generators, creator pool
├── seed.py             # Database seeder for locust tests
├── locustfile.py       # Locust user classes (4 user types, weighted)
├── test_benchmarks.py  # Pytest benchmarks with pass/fail thresholds
└── README.md           # This file
```

### Locust User Distribution

| User Type | Weight | Simulates |
|-----------|--------|-----------|
| `LeaderboardUser` | 40% | Users browsing rankings |
| `SignalUser` | 30% | Traders submitting signals |
| `WebSocketUser` | 20% | Real-time UI connections |
| `BattleUser` | 10% | Battle creation/resolution |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOADTEST_BASE_URL` | `http://localhost:8000` | API base URL |
| `LOADTEST_WS_URL` | `ws://localhost:8000/ws` | WebSocket URL |
| `LOADTEST_NUM_CREATORS` | `20` | Number of test creators to seed |

## Running Against Production

```bash
# Use a test database — never load test against prod data
export DATABASE_URL="postgresql://user:pass@host/tradearena_loadtest"
export LOADTEST_BASE_URL="https://staging.tradearena.io"
export LOADTEST_WS_URL="wss://staging.tradearena.io/ws"
export LOADTEST_NUM_CREATORS=50

uv run python loadtests/seed.py
uv run locust -f loadtests/locustfile.py --headless \
    -u 100 -r 20 --run-time 300s \
    --host $LOADTEST_BASE_URL
```

## Interpreting Results

- **p95 < threshold**: The endpoint meets performance requirements
- **429 responses on signals**: Expected — rate limiting is working correctly
- **409 on battle create**: Expected — duplicate battle detection working
- **WebSocket failures**: Check server connection limits and ping timeout config
