from Backend.database.connection import test_connection as check_database_connection


if __name__ == "__main__":
    try:
        check_database_connection()
    except (ConnectionError, ValueError) as error:
        print(f"Database connection failed: {error}")
        raise SystemExit(1)
    else:
        print("Database connection successful: SELECT 1 returned 1.")
