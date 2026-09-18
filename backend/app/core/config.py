import os

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Portfolio Exposure Graph"
    api_prefix: str = "/api/v1"
    environment: str = "development"
    sec_user_agent: str | None = os.getenv("SEC_USER_AGENT")
    alpha_vantage_api_key: str | None = os.getenv("ALPHA_VANTAGE_API_KEY")


settings = Settings()
