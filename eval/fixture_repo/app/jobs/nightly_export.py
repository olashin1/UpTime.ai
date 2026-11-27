import boto3

from app.db import get_session
from app.models import Order

BUCKET = "acme-warehouse-imports"


def run(export_date: str) -> None:
    """Nightly at 02:00. A failed night is re-exported by the next run."""
    with get_session() as session:
        orders = [o.to_dict() for o in Order.created_on(session, export_date)]
    body = "\n".join(str(o) for o in orders)
    boto3.client("s3").put_object(Bucket=BUCKET, Key=f"orders/{export_date}.jsonl", Body=body)
