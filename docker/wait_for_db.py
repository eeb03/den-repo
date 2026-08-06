"""
Blocks until the database in DATABASE_URL is accepting connections, then
exits 0. Run before `uvicorn` starts so the API never races Postgres's
startup — this makes the container robust regardless of how the
orchestrator's healthcheck timing behaves.
"""
import os
import sys
import time

MAX_ATTEMPTS = 30
SLEEP_SECONDS = 2


def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "sqlite:///./subterra_dev.db")

    if database_url.startswith("sqlite"):
        print("wait_for_db: SQLite in use, nothing to wait for.")
        return

    import psycopg2

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            conn = psycopg2.connect(database_url)
            conn.close()
            print(f"wait_for_db: database is accepting connections (attempt {attempt}).")
            return
        except psycopg2.OperationalError as e:
            print(f"wait_for_db: attempt {attempt}/{MAX_ATTEMPTS} failed ({e}); retrying in {SLEEP_SECONDS}s...")
            time.sleep(SLEEP_SECONDS)

    print("wait_for_db: database never became available. Exiting.")
    sys.exit(1)


if __name__ == "__main__":
    main()
