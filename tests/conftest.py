"""Shared pytest fixtures for the exec-plan test suite."""

import pathlib
import textwrap

import datafusion
import pandas
import pytest

# ── Isolated SessionContext ───────────────────────────────────────────────────


@pytest.fixture()
def ctx() -> datafusion.SessionContext:
    """A fresh, empty DataFusion SessionContext for each test."""
    return datafusion.SessionContext()


# ── In-memory Parquet helper ──────────────────────────────────────────────────


def _make_parquet(df: pandas.DataFrame, path: pathlib.Path) -> pathlib.Path:
    """Write *df* to a Parquet file at *path* and return *path*."""
    df.to_parquet(path)
    return path


# ── Small test tables ─────────────────────────────────────────────────────────


@pytest.fixture()
def orders_parquet(tmp_path: pathlib.Path) -> pathlib.Path:
    """Parquet file with an 'orders' table: id (int), amount (float), status (str)."""
    df = pandas.DataFrame(
        {
            "id": [1, 2, 3, 4, 5],
            "amount": [10.0, 25.5, 7.0, 99.9, 3.3],
            "status": ["open", "closed", "open", "closed", "open"],
        }
    )
    return _make_parquet(df, tmp_path / "orders.parquet")


@pytest.fixture()
def products_parquet(tmp_path: pathlib.Path) -> pathlib.Path:
    """Parquet file with a 'products' table: id (int), name (str), price (float)."""
    df = pandas.DataFrame(
        {
            "id": [1, 2, 3],
            "name": ["widget", "gadget", "doohickey"],
            "price": [9.99, 24.99, 4.99],
        }
    )
    return _make_parquet(df, tmp_path / "products.parquet")


@pytest.fixture()
def ctx_with_orders(
    ctx: datafusion.SessionContext,
    orders_parquet: pathlib.Path,
) -> datafusion.SessionContext:
    """SessionContext with the 'orders' table registered."""
    ctx.register_parquet("orders", orders_parquet)
    return ctx


@pytest.fixture()
def ctx_with_two_tables(
    ctx: datafusion.SessionContext,
    orders_parquet: pathlib.Path,
    products_parquet: pathlib.Path,
) -> datafusion.SessionContext:
    """SessionContext with both 'orders' and 'products' registered."""
    ctx.register_parquet("orders", orders_parquet)
    ctx.register_parquet("products", products_parquet)
    return ctx


# ── CSV helpers ───────────────────────────────────────────────────────────────


@pytest.fixture()
def valid_csv(tmp_path: pathlib.Path) -> pathlib.Path:
    """A well-formed CSV file."""
    p = tmp_path / "valid.csv"
    p.write_text(
        textwrap.dedent("""\
        id,name,value
        1,alice,3.14
        2,bob,2.71
    """)
    )
    return p


@pytest.fixture()
def csv_duplicate_headers(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "dup.csv"
    p.write_text("a,b,a\n1,2,3\n")
    return p


@pytest.fixture()
def csv_blank_header(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "blank.csv"
    p.write_text("id,  ,value\n1,2,3\n")
    return p


@pytest.fixture()
def csv_whitespace_collision(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "ws.csv"
    p.write_text("name ,name,other\n1,2,3\n")
    return p


@pytest.fixture()
def csv_empty(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "empty.csv"
    p.write_text("")
    return p
