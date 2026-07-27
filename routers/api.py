from fastapi import APIRouter

import db
from view_helpers import enrich_product

router = APIRouter()


@router.get("/api/items")
def api_items():
    """Kept at the old /api/items path for compatibility with anything
    already polling it; returns products (each with a nested retailers
    list) rather than the old flat single-retailer rows."""
    return [enrich_product(p) for p in db.list_products()]
