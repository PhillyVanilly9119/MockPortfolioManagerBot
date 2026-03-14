import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from analyst import Analyst
from config import settings
from database import PortfolioSnapshot, Trade, create_tables, get_db
from portfolio_manager import PortfolioManager
from scheduler import TradingScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application-level singletons
# ---------------------------------------------------------------------------

portfolio = PortfolioManager(initial_cash=settings.INITIAL_CASH)
analyst = Analyst()
trading_scheduler = TradingScheduler(portfolio=portfolio, analyst=analyst)


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the data directory and DB tables exist
    os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)
    create_tables()
    trading_scheduler.start()
    logger.info(
        f"MockPortfolioManagerBot online | "
        f"initial cash=${settings.INITIAL_CASH:,.2f} | "
        f"model={settings.OLLAMA_MODEL}"
    )
    yield
    trading_scheduler.stop()
    logger.info("MockPortfolioManagerBot shutting down.")


app = FastAPI(
    title="MockPortfolioManagerBot",
    description="Paper-trading bot for S&P 500 powered by yfinance + Ollama.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health", tags=["System"])
def health():
    """Liveness probe."""
    return {"status": "ok", "model": settings.OLLAMA_MODEL}


@app.get("/portfolio", tags=["Portfolio"])
def get_portfolio():
    """Current holdings, cash balance, and total portfolio value."""
    return portfolio.to_dict(trading_scheduler.current_prices)


@app.get("/benchmark", tags=["Portfolio"])
def get_benchmark():
    """Latest S&P 500 price alongside portfolio total for quick comparison."""
    return {
        "sp500_price": trading_scheduler.sp500_price,
        "portfolio_total": portfolio.total_value(trading_scheduler.current_prices),
        "initial_cash": settings.INITIAL_CASH,
    }


@app.get("/trades", tags=["History"])
def get_trades(limit: int = 50, db: Session = Depends(get_db)):
    """Most-recent executed trades, newest first."""
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="limit must be 1–1000")
    trades = (
        db.query(Trade).order_by(Trade.timestamp.desc()).limit(limit).all()
    )
    return [
        {
            "id": t.id,
            "ticker": t.ticker,
            "action": t.action,
            "shares": t.shares,
            "price": t.price,
            "total_value": t.total_value,
            "reasoning": t.reasoning,
            "timestamp": t.timestamp.isoformat(),
        }
        for t in trades
    ]


@app.get("/snapshots", tags=["History"])
def get_snapshots(limit: int = 200, db: Session = Depends(get_db)):
    """Portfolio performance snapshots, newest first (used for charting)."""
    if limit < 1 or limit > 5000:
        raise HTTPException(status_code=422, detail="limit must be 1–5000")
    snaps = (
        db.query(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": s.id,
            "cash": s.cash,
            "holdings_value": s.holdings_value,
            "total_value": s.total_value,
            "sp500_value": s.sp500_value,
            "timestamp": s.timestamp.isoformat(),
        }
        for s in snaps
    ]


@app.post("/trigger", tags=["System"])
async def trigger_cycle():
    """Manually trigger a trading cycle immediately (useful for testing)."""
    await trading_scheduler.run_now()
    return {"status": "cycle_triggered"}
