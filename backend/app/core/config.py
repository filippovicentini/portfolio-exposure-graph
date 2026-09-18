import os

from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "Portfolio Exposure Graph"
    api_prefix: str = "/api/v1"
    environment: str = "development"
    sec_user_agent: str | None = os.getenv("SEC_USER_AGENT")
    alpha_vantage_api_key: str | None = os.getenv("ALPHA_VANTAGE_API_KEY")
    neo4j_uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user: str = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password: str = os.getenv("NEO4J_PASSWORD", "portfolioexposure")
    neo4j_database: str = os.getenv("NEO4J_DATABASE", "neo4j")


settings = Settings()
