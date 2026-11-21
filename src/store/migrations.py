"""Small, additive SQLite migration for the M1 → M2 schema."""
from sqlalchemy import inspect
from sqlalchemy.engine import Engine


def migrate_fulfillment(engine: Engine) -> None:
    # create_all() creates missing tables, but never adds columns to old ones.
    # Acquire the SQLite write lock before checking so repeated startups are safe.
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        columns = inspect(connection).get_columns("orders")
        if not any(column["name"] == "fulfillment_method" for column in columns):
            connection.exec_driver_sql(
                "ALTER TABLE orders ADD COLUMN fulfillment_method "
                "VARCHAR(30) NOT NULL DEFAULT 'standard'"
            )
