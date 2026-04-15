from fastapi import APIRouter

from app.db.insight_db import insight_db

router = APIRouter()


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "DataLens Analytics",
        "cosmos_ready": insight_db.is_ready,
    }
