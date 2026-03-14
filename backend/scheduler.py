import logging
import random

import pandas as pd
import yfinance as yf
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

from analyst import Analyst
from config import settings
from database import SessionLocal
from portfolio_manager import PortfolioManager

logger = logging.getLogger(__name__)

# Curated S&P 500 sample — a diverse cross-sector watchlist lightweight
# enough for a Raspberry Pi 5.
WATCHLIST: list[str] = [
    # Tech
    "AAPL", "MSFT", "GOOGL", "NVDA", "META",
    # Consumer / Retail
    "AMZN", "TSLA", "HD", "NKE", "MCD",
    # Finance
    "JPM", "BAC", "V", "MA", "BRK-B",
    # Healthcare
    "JNJ", "UNH", "PFE", "ABBV", "MRK",
    # Energy / Industrials
    "XOM", "CVX", "CAT", "GE", "HON",
]


class TradingScheduler:
    """
    Periodically fetches price/news data, calls the Analyst for a
    BUY/SELL/HOLD decision, and updates the PortfolioManager.
    """

    def __init__(self, portfolio: PortfolioManager, analyst: Analyst) -> None:
        self.portfolio = portfolio
        self.analyst = analyst
        self._scheduler = AsyncIOScheduler()
        self._current_prices: dict[str, float] = {}
        self._sp500_price: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._scheduler.add_job(
            self._run_cycle,
            trigger="interval",
            minutes=settings.FETCH_INTERVAL_MINUTES,
            id="trading_cycle",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info(
            f"Scheduler started — trading cycle every "
            f"{settings.FETCH_INTERVAL_MINUTES} minute(s)."
        )

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Public read-only state
    # ------------------------------------------------------------------

    @property
    def current_prices(self) -> dict[str, float]:
        return self._current_prices

    @property
    def sp500_price(self) -> float:
        return self._sp500_price

    # ------------------------------------------------------------------
    # Core trading cycle
    # ------------------------------------------------------------------

    async def run_now(self) -> None:
        """Trigger a cycle immediately (used by the manual-trigger endpoint)."""
        await self._run_cycle()

    async def _run_cycle(self) -> None:
        logger.info("=== Trading cycle started ===")
        db: Session = SessionLocal()
        try:
            # 1. Refresh prices for the full watchlist
            self._current_prices = self._fetch_prices(WATCHLIST)
            self._sp500_price = self._fetch_price(settings.SP500_BENCHMARK_TICKER)

            # 2. Pick a random sample to analyse this cycle (saves CPU)
            tickers_to_analyse = random.sample(
                WATCHLIST, min(settings.TICKERS_PER_CYCLE, len(WATCHLIST))
            )

            for ticker in tickers_to_analyse:
                price = self._current_prices.get(ticker)
                if not price or price <= 0:
                    logger.debug(f"No price for {ticker}, skipping.")
                    continue

                news = self._fetch_news(ticker)
                financials = self._fetch_financials_summary(ticker)

                decision = await self.analyst.analyze(ticker, price, news, financials)
                action = decision["action"]
                tldr = decision["tldr"]

                if action == "BUY":
                    self.portfolio.buy(
                        ticker,
                        price,
                        allocation_pct=settings.POSITION_ALLOCATION_PCT,
                        db=db,
                        tldr=tldr,
                    )
                elif action == "SELL":
                    self.portfolio.sell(ticker, price, db=db, tldr=tldr)
                else:
                    logger.info(f"HOLD {ticker:6s} @ ${price:.2f}  — {tldr}")

            # 3. Persist a portfolio snapshot for the performance chart
            self.portfolio.snapshot(self._current_prices, self._sp500_price, db)

        except Exception:
            logger.exception("Unhandled error in trading cycle")
        finally:
            db.close()
            logger.info("=== Trading cycle complete ===")

    # ------------------------------------------------------------------
    # yfinance helpers (all synchronous — called from async context is ok
    # because they are I/O-bound and the scheduler runs them in the event
    # loop; for heavy usage a thread executor could be used instead)
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_prices(tickers: list[str]) -> dict[str, float]:
        prices: dict[str, float] = {}
        try:
            data = yf.download(
                tickers,
                period="1d",
                interval="1m",
                progress=False,
                auto_adjust=True,
            )
            if data.empty:
                return prices

            close = data["Close"]

            if isinstance(close, pd.DataFrame):
                last = close.ffill().iloc[-1]
                for t in tickers:
                    if t in last.index and pd.notna(last[t]):
                        prices[t] = float(last[t])
            elif isinstance(close, pd.Series):
                # yfinance returns a Series when only one ticker was passed
                val = close.ffill().iloc[-1]
                if pd.notna(val) and tickers:
                    prices[tickers[0]] = float(val)

        except Exception as exc:
            logger.warning(f"Bulk price fetch error: {exc}")
        return prices

    @staticmethod
    def _fetch_price(ticker: str) -> float:
        try:
            data = yf.download(
                ticker,
                period="1d",
                interval="1m",
                progress=False,
                auto_adjust=True,
            )
            if data.empty:
                return 0.0
            return float(data["Close"].ffill().iloc[-1])
        except Exception as exc:
            logger.warning(f"Single price fetch error ({ticker}): {exc}")
            return 0.0

    @staticmethod
    def _fetch_news(ticker: str) -> list[str]:
        try:
            t = yf.Ticker(ticker)
            news_items = t.news or []
            return [
                item.get("title", "")
                for item in news_items[:5]
                if item.get("title")
            ]
        except Exception:
            return []

    @staticmethod
    def _fetch_financials_summary(ticker: str) -> str:
        try:
            info = yf.Ticker(ticker).info
            return (
                f"PE={info.get('trailingPE', 'N/A')}, "
                f"EPS={info.get('trailingEps', 'N/A')}, "
                f"Revenue={info.get('totalRevenue', 'N/A')}, "
                f"MarketCap={info.get('marketCap', 'N/A')}, "
                f"52W_High={info.get('fiftyTwoWeekHigh', 'N/A')}, "
                f"52W_Low={info.get('fiftyTwoWeekLow', 'N/A')}, "
                f"Sector={info.get('sector', 'N/A')}"
            )
        except Exception:
            return "Financials unavailable."
