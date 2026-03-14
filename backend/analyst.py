import json
import logging

import httpx

from config import settings

logger = logging.getLogger(__name__)


class Analyst:
    """
    Sends structured market data to a local Ollama LLM and parses the
    JSON decision it returns.
    """

    def __init__(self) -> None:
        self._base_url = settings.OLLAMA_BASE_URL
        self._model = settings.OLLAMA_MODEL

    async def analyze(
        self,
        ticker: str,
        price: float,
        news_snippets: list[str],
        financials_summary: str,
    ) -> dict:
        """
        Returns a dict with keys:
          action      – "BUY" | "SELL" | "HOLD"
          confidence  – float 0–1
          tldr        – one-sentence reasoning string
        """
        prompt = self._build_prompt(ticker, price, news_snippets, financials_summary)
        raw = await self._query_ollama(prompt)
        return self._parse_response(raw)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        ticker: str,
        price: float,
        news_snippets: list[str],
        financials_summary: str,
    ) -> str:
        news_block = "\n".join(f"  - {s}" for s in news_snippets[:5]) or "  (no news)"
        return f"""You are a concise, data-driven stock analyst.
Analyse the information below and output a trading recommendation.

Ticker: {ticker}
Current Price: ${price:.2f}

Recent Headlines:
{news_block}

Key Financials:
  {financials_summary}

Respond ONLY with a single valid JSON object — no markdown, no extra text:
{{
  "action": "<BUY|SELL|HOLD>",
  "confidence": <0.0-1.0>,
  "tldr": "<one concise sentence explaining the decision>"
}}"""

    async def _query_ollama(self, prompt: str) -> str:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._base_url}/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    # Disable chain-of-thought for qwen3 models to keep
                    # output clean and fast on low-power hardware.
                    "options": {"temperature": 0.3},
                },
            )
            response.raise_for_status()
            return response.json()["response"]

    @staticmethod
    def _parse_response(raw: str) -> dict:
        fallback = {
            "action": "HOLD",
            "confidence": 0.0,
            "tldr": "LLM response could not be parsed — defaulting to HOLD.",
        }
        try:
            data = json.loads(raw)
            action = str(data.get("action", "HOLD")).upper().strip()
            if action not in {"BUY", "SELL", "HOLD"}:
                action = "HOLD"
            return {
                "action": action,
                "confidence": float(data.get("confidence", 0.5)),
                "tldr": str(data.get("tldr", "No reasoning provided.")),
            }
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(f"Analyst parse error: {exc} | raw='{raw[:200]}'")
            return fallback
