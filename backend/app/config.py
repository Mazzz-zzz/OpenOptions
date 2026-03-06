from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "openoptions"
    db_user: str = "postgres"
    db_password: str = "postgres"

    # API keys (via env vars — no Secrets Manager for MVP)
    deribit_client_id: str = ""
    deribit_client_secret: str = ""
    tastytrade_client_id: str = ""
    tastytrade_client_secret: str = ""
    tastytrade_refresh_token: str = ""

    # FRED
    fred_api_key: str = ""

    # Thresholds
    vol_threshold: float = 2.0

    # Security — comma-separated IP whitelist (empty = allow all)
    allowed_ips_csv: str = ""

    @property
    def allowed_ips(self) -> set:
        if not self.allowed_ips_csv:
            return set()
        return {ip.strip() for ip in self.allowed_ips_csv.split(",") if ip.strip()}

    # General
    environment: str = "development"
    market_tz: str = "America/New_York"

    class Config:
        env_file = ".env"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
