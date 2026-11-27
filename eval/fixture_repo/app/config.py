import os


class Settings:
    database_url = os.environ.get("DATABASE_URL", "postgresql://shop@localhost/shop")
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    payment_api_key = os.environ.get("PAYMENT_API_KEY", "")
    payment_refund_key = os.environ.get("PAYMENT_REFUND_KEY", "")
    payment_webhook_secret = os.environ.get("PAYMENT_WEBHOOK_SECRET", "")
    jwt_public_key = os.environ.get("JWT_PUBLIC_KEY", "")
    environment = os.environ.get("ENVIRONMENT", "development")


settings = Settings()
