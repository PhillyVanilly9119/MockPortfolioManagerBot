# MockPortfolioManagerBot

A paper-trading bot for the S&P 500 that runs entirely on a **Raspberry Pi 5**.  
No external API keys required. All reasoning is done locally via [Ollama](https://ollama.com/).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  Raspberry Pi 5 (Docker)                │
│                                                         │
│  ┌──────────┐    HTTP     ┌──────────────────────────┐  │
│  │ Streamlit│───────────▶│  FastAPI  (port 8000)    │  │
│  │ Dashboard│             │  ├─ Scheduler (APSched)  │  │
│  │ port 8501│             │  ├─ PortfolioManager      │  │
│  └──────────┘             │  ├─ Analyst               │  │
│                           │  └─ SQLite DB (/data/)   │  │
│                           └────────────┬─────────────┘  │
│                                        │ HTTP /api/gen   │
│                           ┌────────────▼─────────────┐  │
│                           │  Ollama  (port 11434)     │  │
│                           │  Model: qwen3:4b          │  │
│                           └──────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

| Component | Technology |
|---|---|
| Market data & news | `yfinance` (no API key) |
| LLM reasoning | Ollama · `qwen3:4b` or `phi4-mini` |
| Backend API | FastAPI + APScheduler |
| Database | SQLite (via SQLAlchemy) |
| Frontend | Streamlit + Plotly |
| Deployment | Docker Compose (linux/arm64) |

---

## Directory Structure

```
MockPortfolioManagerBot/
├── docker-compose.yml
├── data/                   ← SQLite DB lives here (host-mounted volume)
│   └── .gitkeep
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── config.py           ← All settings (env-var overridable)
│   ├── database.py         ← SQLAlchemy models + session helpers
│   ├── analyst.py          ← Ollama integration + prompt builder
│   ├── portfolio_manager.py← Fake cash, holdings, P&L tracking
│   ├── scheduler.py        ← APScheduler trading cycle + yfinance calls
│   └── main.py             ← FastAPI app + REST endpoints
└── frontend/
    ├── Dockerfile
    ├── requirements.txt
    └── app.py              ← Streamlit dashboard
```

---

## Quick Start (Raspberry Pi 5)

### Prerequisites

- Docker & Docker Compose installed on the Pi  
  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo apt-get install -y docker-compose-plugin
  ```
- At least **6 GB free disk space** for the Ollama model weights
- At least **4 GB RAM** recommended (Pi 5 with 8 GB is ideal)

### 1 — Pull the LLM model

The `ollama` container must download the model weights before the backend
can make its first analysis call.  Start Ollama first, then pull the model:

```bash
# Start only Ollama
docker compose up -d ollama

# Pull qwen3:4b (~2.6 GB, Q4_K_M) — takes a few minutes on first run
docker exec -it ollama ollama pull qwen3:4b

# Alternative lighter model (~2.2 GB)
# docker exec -it ollama ollama pull phi4-mini
```

> To switch models, change `OLLAMA_MODEL` in `docker-compose.yml`.

### 2 — Start the full stack

```bash
docker compose up -d
```

| Service | URL |
|---|---|
| Streamlit Dashboard | http://<pi-ip>:8501 |
| FastAPI (Swagger UI) | http://<pi-ip>:8000/docs |
| Ollama API | http://<pi-ip>:11434 |

### 3 — Trigger the first trading cycle manually

```bash
curl -X POST http://localhost:8000/trigger
```

Or click **⚡ Trigger Trading Cycle** in the Streamlit sidebar.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `GET` | `/portfolio` | Holdings, cash, total value |
| `GET` | `/benchmark` | S&P 500 price vs portfolio total |
| `GET` | `/trades?limit=50` | Recent trade history with TL;DR reasoning |
| `GET` | `/snapshots?limit=200` | Performance snapshots for charting |
| `POST` | `/trigger` | Manually run a trading cycle immediately |

---

## Configuration

All settings are in [backend/config.py](backend/config.py) and can be
overridden via environment variables in `docker-compose.yml`:

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_MODEL` | `qwen3:4b` | LLM model name |
| `INITIAL_CASH` | `100000.0` | Starting paper-money balance |
| `FETCH_INTERVAL_MINUTES` | `10` | Scheduler interval |
| `TICKERS_PER_CYCLE` | `5` | Tickers analysed per cycle |
| `POSITION_ALLOCATION_PCT` | `0.05` | Max cash % spent per BUY (5 %) |

---

## How It Works

1. **Scheduler** fires every `FETCH_INTERVAL_MINUTES`.  
2. Prices are fetched for the full 25-ticker watchlist via `yfinance.download()`.  
3. A random sample of `TICKERS_PER_CYCLE` tickers is selected.  
4. For each ticker, `yfinance.Ticker.news` and `.info` financials are fetched.  
5. The **Analyst** builds a structured prompt and sends it to Ollama (`/api/generate`).  
6. Ollama returns a JSON object: `{ action, confidence, tldr }`.  
7. **PortfolioManager** executes BUY/SELL and writes the trade + TL;DR to SQLite.  
8. A **portfolio snapshot** is saved for the performance chart.  

---

## Disclaimer

This is a **mock / paper-trading** simulator for educational and demonstration
purposes only. It does not constitute financial advice and no real money is
involved.

