from fastapi import APIRouter
from quickquip.app.message_pipeline import stats_tracker

router = APIRouter()


@router.get("/stats")
def get_stats():
    return stats_tracker.to_dict()
