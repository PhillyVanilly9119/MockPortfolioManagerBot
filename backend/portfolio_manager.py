import logging
from typing import Optional

from sqlalchemy.orm import Session

from database import PortfolioSnapshot, Trade

logger = logging.getLogger(__name__)


class PortfolioManager:
    """
    Tracks fake cash, equity positions, and performance.
    All mutations are persisted to SQLite via the provided session.
    """

    def __init__(self, initial_cash: float) -> None:
        self._cash: float = initial_cash
        # ticker -> {"shares": float, "avg_price": float}
        self._holdings: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def holdings(self) -> dict:
        return self._holdings

    def holdings_value(self, current_prices: dict[str, float]) -> float:
        return sum(
            data["shares"] * current_prices.get(ticker, data["avg_price"])
            for ticker, data in self._holdings.items()
        )

    def total_value(self, current_prices: dict[str, float]) -> float:
        return self._cash + self.holdings_value(current_prices)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def buy(
        self,
        ticker: str,
        price: float,
        allocation_pct: float,
        db: Session,
        tldr: str,
    ) -> Optional[dict]:
        """
        Spend up to `allocation_pct` of remaining cash on `ticker`.
        Returns None if there is insufficient cash.
        """
        if price <= 0:
            return None
        spend = self._cash * allocation_pct
        if spend < price:
            logger.debug(f"Skipping BUY {ticker}: insufficient cash (have ${self._cash:.2f})")
            return None

        shares = spend / price
        self._cash -= shares * price

        if ticker in self._holdings:
            existing = self._holdings[ticker]
            total_shares = existing["shares"] + shares
            self._holdings[ticker] = {
                "shares": total_shares,
                "avg_price": (
                    existing["shares"] * existing["avg_price"] + shares * price
                )
                / total_shares,
            }
        else:
            self._holdings[ticker] = {"shares": shares, "avg_price": price}

        trade = Trade(
            ticker=ticker,
            action="BUY",
            shares=shares,
            price=price,
            total_value=shares * price,
            reasoning=tldr,
        )
        db.add(trade)
        db.commit()
        logger.info(f"BUY  {ticker:6s}  {shares:.4f} shares @ ${price:.2f}  — {tldr}")
        return {"action": "BUY", "shares": shares, "price": price}

    def sell(
        self,
        ticker: str,
        price: float,
        db: Session,
        tldr: str,
    ) -> Optional[dict]:
        """Liquidate the full position in `ticker`. Returns None if not held."""
        if ticker not in self._holdings:
            return None

        shares = self._holdings[ticker]["shares"]
        proceeds = shares * price
        self._cash += proceeds
        del self._holdings[ticker]

        trade = Trade(
            ticker=ticker,
            action="SELL",
            shares=shares,
            price=price,
            total_value=proceeds,
            reasoning=tldr,
        )
        db.add(trade)
        db.commit()
        logger.info(f"SELL {ticker:6s}  {shares:.4f} shares @ ${price:.2f}  — {tldr}")
        return {"action": "SELL", "shares": shares, "price": price}

    def snapshot(
        self,
        current_prices: dict[str, float],
        sp500_value: float,
        db: Session,
    ) -> None:
        snap = PortfolioSnapshot(
            cash=self._cash,
            holdings_value=self.holdings_value(current_prices),
            total_value=self.total_value(current_prices),
            sp500_value=sp500_value,
        )
        db.add(snap)
        db.commit()

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self, current_prices: dict[str, float]) -> dict:
        positions = []
        for ticker, data in self._holdings.items():
            price = current_prices.get(ticker, data["avg_price"])
            cost = data["avg_price"]
            pnl_pct = ((price - cost) / cost) * 100 if cost else 0.0
            positions.append(
                {
                    "ticker": ticker,
                    "shares": round(data["shares"], 6),
                    "avg_price": round(cost, 4),
                    "current_price": round(price, 4),
                    "market_value": round(data["shares"] * price, 2),
                    "pnl_pct": round(pnl_pct, 2),
                }
            )
        # Sort by market value descending for readability
        positions.sort(key=lambda p: p["market_value"], reverse=True)
        return {
            "cash": round(self._cash, 2),
            "holdings_value": round(self.holdings_value(current_prices), 2),
            "total_value": round(self.total_value(current_prices), 2),
            "positions": positions,
        }
