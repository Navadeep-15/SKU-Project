import os
from typing import Optional

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_connection(database_url: Optional[str] = None) -> psycopg.Connection:
    """Open and return a PostgreSQL connection using DATABASE_URL."""
    if database_url is None:
        database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is not set. Configure it in the environment or .env.")

    try:
        return psycopg.connect(database_url, connect_timeout=10)
    except psycopg.Error:
        raise ConnectionError(
            "Unable to connect to PostgreSQL. Check DATABASE_URL and database availability."
        ) from None


def test_connection() -> bool:
    """Run a simple query to verify database connectivity."""
    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
    except psycopg.Error:
        raise ConnectionError(
            "Database connection test failed. Check DATABASE_URL and database availability."
        ) from None

    if result != (1,):
        raise ConnectionError("Database connection test did not return the expected result.")

    return True
