from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.dependencies import enrichment_queue, enrichment_service
from app.domain.enums import EnrichmentJobStatus
from app.domain.models import EnrichmentJob, EnrichmentProcessResult

router = APIRouter(prefix="/enrichment-jobs", tags=["enrichment"])


@router.get("", response_model=list[EnrichmentJob])
def list_enrichment_jobs(
    status: EnrichmentJobStatus | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[EnrichmentJob]:
    return enrichment_queue.list(status=status, limit=limit)


@router.post("/process", response_model=EnrichmentProcessResult)
def process_enrichment_jobs(
    limit: int = Query(default=10, ge=1, le=50),
) -> EnrichmentProcessResult:
    return enrichment_service.process(limit=limit)


@router.get("/{job_id}", response_model=EnrichmentJob)
def get_enrichment_job(job_id: UUID) -> EnrichmentJob:
    job = enrichment_queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Enrichment job not found")
    return job
