"""One-off: convert old v1 coupon codes into PromoCode rows. Run manually by staff."""
import sentry_sdk

from app.db import get_session
from app.legacy.v1_coupons import parse_v1_code
from app.models import PromoCode


def main(codes: list[str]) -> None:
    sentry_sdk.init()
    with get_session() as session:
        for code in codes:
            PromoCode.create(session, code=code, rules=parse_v1_code(code))
