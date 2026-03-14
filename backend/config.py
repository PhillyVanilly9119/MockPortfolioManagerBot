from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Ollama
    OLLAMA_BASE_URL: str = "http://ollama:11434"
    OLLAMA_MODEL: str = "qwen3:4b"

    # Database
    DB_PATH: str = "/data/portfolio.db"

    # Portfolio
    INITIAL_CASH: float = 100_000.0

    # Scheduler
    FETCH_INTERVAL_MINUTES: int = 10

    # Benchmark
    SP500_BENCHMARK_TICKER: str = "^GSPC"

    # How many tickers to analyse per cycle (keeps Pi CPU usage sane)
    TICKERS_PER_CYCLE: int = 5

    # Max allocation per position as a fraction of available cash
    POSITION_ALLOCATION_PCT: float = 0.05


settings = Settings()
