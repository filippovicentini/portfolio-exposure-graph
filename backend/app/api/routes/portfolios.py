from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.dependencies import graph_service, lookthrough_service, portfolio_service
from app.domain.models import (
    CompanyFilingsSyncResult,
    CompanyMetadataSyncResult,
    GraphSyncResult,
    Portfolio,
    PortfolioCreate,
    PortfolioExposurePaths,
    PortfolioLookthrough,
    PortfolioStructuralExposure,
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


@router.post(
    "/{portfolio_id}/graph/company-metadata/sync",
    response_model=CompanyMetadataSyncResult,
)
def sync_portfolio_company_metadata(
    portfolio_id: UUID,
    limit: int = Query(default=25, ge=1, le=100),
) -> CompanyMetadataSyncResult:
    result = graph_service.sync_company_metadata(portfolio_id, limit=limit)
    if result is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return result


@router.post(
    "/{portfolio_id}/graph/sec-filings/sync",
    response_model=CompanyFilingsSyncResult,
)
def sync_portfolio_sec_filings(
    portfolio_id: UUID,
    company_limit: int = Query(default=5, ge=1, le=25),
    filings_per_company: int = Query(default=4, ge=1, le=20),
) -> CompanyFilingsSyncResult:
    result = graph_service.sync_company_filings(
        portfolio_id,
        company_limit=company_limit,
        filings_per_company=filings_per_company,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return result


@router.get("/{portfolio_id}/graph/paths", response_model=PortfolioExposurePaths)
def get_portfolio_graph_paths(portfolio_id: UUID) -> PortfolioExposurePaths:
    result = graph_service.get_paths(portfolio_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return result


@router.get(
    "/{portfolio_id}/graph/structural-exposure",
    response_model=PortfolioStructuralExposure,
)
def get_portfolio_structural_exposure(
    portfolio_id: UUID,
) -> PortfolioStructuralExposure:
    result = graph_service.get_structural_exposure(portfolio_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return result
