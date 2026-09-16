from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Portfolio Exposure Graph"
    api_prefix: str = "/api/v1"
    environment: str = "development"


settings = Settings()
