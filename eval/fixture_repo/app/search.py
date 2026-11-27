import httpx
import sentry_sdk
from fastapi import APIRouter, HTTPException

from app.db import get_session
from app.models import Product

router = APIRouter()
SEARCH_URL = "http://search.internal.acme:9200/products/_search"


@router.get("/search")
def search_products(q: str):
    if any(token in q for token in ["'", "--", ";"]):
        raise HTTPException(status_code=400, detail="Invalid query")
    try:
        response = httpx.post(SEARCH_URL, json={"query": {"match": {"name": q}}}, timeout=1)
        response.raise_for_status()
        return [hit["_source"] for hit in response.json()["hits"]["hits"]]
    except httpx.HTTPError as exc:
        # Slower and less relevant, but results still come back.
        sentry_sdk.capture_exception(exc)
        with get_session() as session:
            return Product.name_like(session, q, limit=50)
