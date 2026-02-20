"""
DB types that work on both SQLite (for local testing) and PostgreSQL.
Use these in models so the app runs without Docker when DATABASE_URL is sqlite:///...
"""
import uuid
from sqlalchemy import String, TypeDecorator


class UuidType(TypeDecorator):
    """UUID that stores as string(36) so it works on SQLite and PostgreSQL."""
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)
