from fastapi import APIRouter, Query, HTTPException
from backend.data_sources.factory import list_data_sources, switch_data_source, get_data_source

router = APIRouter(prefix="/api/v1/data-sources", tags=["data-sources"])


@router.get("")
def get_sources():
    ds = get_data_source()
    return {"active": ds.name, "available": list_data_sources()}


@router.post("/switch")
def switch_source(source: str = Query(...)):
    try:
        switch_data_source(source)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"active": source}
