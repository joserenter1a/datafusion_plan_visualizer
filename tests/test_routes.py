"""Tests for server.routes — HTTP contract and SQL injection protection."""

import io
import pathlib

import pandas
import pytest
from fastapi.testclient import TestClient

import engine.context as ctx_mod
from server.app import app
from server.routes import _assert_select_only

# ── _assert_select_only (unit) ────────────────────────────────────────────────


class TestAssertSelectOnly:
    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            _assert_select_only("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            _assert_select_only("   ")

    @pytest.mark.parametrize(
        "stmt",
        [
            "DROP TABLE orders",
            "INSERT INTO orders VALUES (1, 10.0, 'open')",
            "UPDATE orders SET status = 'x'",
            "DELETE FROM orders",
            "CREATE VIEW v AS SELECT 1",
            "ALTER TABLE orders ADD COLUMN x INT",
        ],
    )
    def test_ddl_dml_blocked(self, stmt: str) -> None:
        with pytest.raises(ValueError, match="not allowed"):
            _assert_select_only(stmt)

    def test_statement_stacking_blocked(self) -> None:
        with pytest.raises(ValueError, match="Multiple"):
            _assert_select_only("SELECT 1; DROP TABLE orders")

    def test_trailing_semicolon_allowed(self) -> None:
        _assert_select_only("SELECT 1;")  # must not raise

    @pytest.mark.parametrize(
        "stmt",
        [
            "SELECT 1",
            "select id from orders",
            "WITH cte AS (SELECT 1) SELECT * FROM cte",
            "EXPLAIN SELECT id FROM orders",
        ],
    )
    def test_permitted_statements_pass(self, stmt: str) -> None:
        _assert_select_only(stmt)  # must not raise


# ── HTTP integration (TestClient) ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    """TestClient with an isolated DataFusion context pre-loaded with 'orders'."""
    tmp = tmp_path_factory.mktemp("data")

    parquet = tmp / "orders.parquet"
    pandas.DataFrame(
        {
            "id": [1, 2, 3],
            "amount": [10.0, 25.5, 7.0],
            "status": ["open", "closed", "open"],
        }
    ).to_parquet(parquet)

    fresh_ctx = __import__("datafusion").SessionContext()
    fresh_ctx.register_parquet("orders", parquet)

    import unittest.mock as mock

    with mock.patch.object(ctx_mod, "context", fresh_ctx):
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


class TestGetTables:
    def test_returns_tables_key(self, client: TestClient) -> None:
        resp = client.get("/tables")
        assert resp.status_code == 200
        assert "tables" in resp.json()

    def test_orders_listed(self, client: TestClient) -> None:
        tables = {t["name"] for t in client.get("/tables").json()["tables"]}
        assert "orders" in tables

    def test_schema_columns_present(self, client: TestClient) -> None:
        tables = client.get("/tables").json()["tables"]
        orders = next(t for t in tables if t["name"] == "orders")
        col_names = {c["name"] for c in orders["columns"]}
        assert {"id", "amount", "status"} <= col_names


class TestPostPlan:
    @pytest.mark.parametrize("plan_type", ["logical", "optimized", "physical"])
    def test_single_plan_response(self, client: TestClient, plan_type: str) -> None:
        resp = client.post(
            "/plan", json={"sql": "SELECT id FROM orders", "plan_type": plan_type}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "single"
        assert isinstance(body["elements"], list)
        assert len(body["elements"]) > 0

    def test_diff_plan_response(self, client: TestClient) -> None:
        resp = client.post(
            "/plan", json={"sql": "SELECT id FROM orders", "plan_type": "diff"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "diff"
        assert isinstance(body["left"], list)
        assert isinstance(body["right"], list)

    def test_invalid_sql_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/plan", json={"sql": "NOT VALID SQL !!!", "plan_type": "logical"}
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        "stmt",
        [
            "DROP TABLE orders",
            "INSERT INTO orders VALUES (1, 10.0, 'open')",
            "SELECT 1; DROP TABLE orders",
        ],
    )
    def test_injection_attempts_return_400(self, client: TestClient, stmt: str) -> None:
        resp = client.post("/plan", json={"sql": stmt, "plan_type": "logical"})
        assert resp.status_code == 400
        assert (
            "not allowed" in resp.json()["detail"]
            or "Multiple" in resp.json()["detail"]
        )

    def test_default_plan_type_is_logical(self, client: TestClient) -> None:
        resp = client.post("/plan", json={"sql": "SELECT id FROM orders"})
        assert resp.status_code == 200
        assert resp.json()["type"] == "single"


class TestUploadTable:
    def test_upload_valid_csv(self, client: TestClient, tmp_path: pathlib.Path) -> None:
        csv_content = b"x,y\n1,2\n3,4\n"
        resp = client.post(
            "/tables",
            files={"file": ("mydata.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["registered"] == "mydata"
        assert any(t["name"] == "mydata" for t in body["tables"])

    def test_upload_unsupported_extension_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/tables",
            files={
                "file": ("data.xlsx", io.BytesIO(b"fake"), "application/octet-stream")
            },
        )
        assert resp.status_code == 400
        assert ".xlsx" in resp.json()["detail"]

    def test_upload_duplicate_headers_csv_returns_400(self, client: TestClient) -> None:
        csv_content = b"col,col\n1,2\n"
        resp = client.post(
            "/tables",
            files={"file": ("bad.csv", io.BytesIO(csv_content), "text/csv")},
        )
        assert resp.status_code == 400
        assert "Duplicate" in resp.json()["detail"]


class TestDeleteTable:
    def test_delete_existing_table(self, client: TestClient) -> None:
        # First upload a throwaway table
        csv_content = b"a,b\n1,2\n"
        client.post(
            "/tables",
            files={"file": ("throwaway.csv", io.BytesIO(csv_content), "text/csv")},
        )

        resp = client.delete("/tables/throwaway")
        assert resp.status_code == 200
        remaining = {t["name"] for t in resp.json()["tables"]}
        assert "throwaway" not in remaining

    def test_delete_nonexistent_table_returns_404(self, client: TestClient) -> None:
        resp = client.delete("/tables/does_not_exist")
        assert resp.status_code == 404
