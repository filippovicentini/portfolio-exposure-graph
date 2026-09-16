from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.domain.models import Portfolio, PortfolioCreate
from app.dependencies import portfolio_service

router = APIRouter(prefix="/portfolios", tags=["portfolios"])


@router.post("", response_model=Portfolio, status_code=status.HTTP_201_CREATED)
def create_portfolio(payload: PortfolioCreate) -> Portfolio:
    return portfolio_service.create(payload)


@router.get("/{portfolio_id}", response_model=Portfolio)
def get_portfolio(portfolio_id: UUID) -> Portfolio:
    portfolio = portfolio_service.get(portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio
