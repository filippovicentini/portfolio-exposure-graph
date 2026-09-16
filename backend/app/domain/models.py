from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import AssetStatus, AssetType, PortfolioStatus


class PositionInput(BaseModel):
    ticker: str = Field(min_length=1, max_length=24)
    weight_pct: float = Field(gt=0, le=100)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    positions: list[PositionInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_positions(self) -> "PortfolioCreate":
        tickers = [position.ticker for position in self.positions]
        if len(set(tickers)) != len(tickers):
            raise ValueError("Duplicate tickers are not allowed")

        total = sum(position.weight_pct for position in self.positions)
        if abs(total - 100.0) > 0.01:
            raise ValueError(f"Portfolio weights must sum to 100%; got {total:.2f}%")
        return self


class AssetResolution(BaseModel):
    asset_id: UUID = Field(default_factory=uuid4)
    ticker: str
    exchange: str | None = None
    asset_type: AssetType = AssetType.UNKNOWN
    status: AssetStatus
    company_name: str | None = None


class PortfolioPosition(BaseModel):
    ticker: str
    weight_pct: float
    asset: AssetResolution


class EnrichmentJob(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    ticker: str
    status: str = "queued"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Portfolio(BaseModel):
    portfolio_id: UUID = Field(default_factory=uuid4)
    name: str
    status: PortfolioStatus
    positions: list[PortfolioPosition]
    enrichment_jobs: list[EnrichmentJob] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
