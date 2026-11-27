"""v1 coupon format (pre-2024). No API route uses this module any more; it is only
imported by scripts/backfill_coupons.py, which staff run by hand."""


def parse_v1_code(code: str) -> dict:
    prefix, pct = code.split("-")
    return {"prefix": prefix, "discount_pct": int(pct)}
