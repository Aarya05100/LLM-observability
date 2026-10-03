from fastapi import APIRouter
from app.storage.memory_store import MemoryStore

router = APIRouter()
store = MemoryStore()

@router.get("/costs")
async def get_costs():
    return {
        "cost_by_feature": store.get_cost_by_feature(),
        "cost_by_model": store.get_cost_by_model(),
    }

@router.get("/spans")
async def get_spans():
    return {"spans": store.get_all_spans()}
