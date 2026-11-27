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


def migrate_marketplace(engine: Engine) -> None:
    """Add marketplace provenance and unique external IDs without losing M2 data."""
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        columns = {column["name"] for column in inspect(connection).get_columns("orders")}
        if "order_source" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE orders ADD COLUMN order_source "
                "VARCHAR(30) NOT NULL DEFAULT 'storefront'"
            )
        if "marketplace_order_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE orders ADD COLUMN marketplace_order_id VARCHAR(120)"
            )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_marketplace_order_id "
            "ON orders (marketplace_order_id)"
        )
