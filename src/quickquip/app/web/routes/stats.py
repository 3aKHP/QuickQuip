from fastapi import APIRouter

router = APIRouter()


@router.get("/stats")
def get_stats():
    from quickquip.app.message_pipeline import stats_tracker

    return stats_tracker.to_dict()
