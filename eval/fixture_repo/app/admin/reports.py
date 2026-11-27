from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.auth import require_staff
from app.db import get_session

router = APIRouter(prefix="/admin")


@router.get("/reports/sales")
def sales_report(days: int = 365, staff=Depends(require_staff)):
    """Internal report for the ops team. Not linked from the storefront."""
    with get_session() as session:
        rows = session.execute(
            text(
                "SELECT date_trunc('day', created_at) d, sum(total) FROM orders "
                "WHERE created_at > now() - make_interval(days => :days) GROUP BY d"
            ),
            {"days": days},
        ).all()
    return [{"day": str(d), "revenue": float(total)} for d, total in rows]
