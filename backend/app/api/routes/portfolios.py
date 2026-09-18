from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.dependencies import graph_service, lookthrough_service, portfolio_service
from app.domain.models import (
    GraphSyncResult,
    Portfolio,
    PortfolioCreate,
    PortfolioExposurePaths,
    PortfolioLookthrough,
)

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


@router.get("/{portfolio_id}/lookthrough", response_model=PortfolioLookthrough)
def get_portfolio_lookthrough(portfolio_id: UUID) -> PortfolioLookthrough:
    lookthrough = lookthrough_service.calculate(portfolio_id)
    if lookthrough is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return lookthrough


@router.post("/{portfolio_id}/graph/sync", response_model=GraphSyncResult)
def sync_portfolio_graph(portfolio_id: UUID) -> GraphSyncResult:
    result = graph_service.sync(portfolio_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return result


@router.get("/{portfolio_id}/graph/paths", response_model=PortfolioExposurePaths)
def get_portfolio_graph_paths(portfolio_id: UUID) -> PortfolioExposurePaths:
    result = graph_service.get_paths(portfolio_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return result
