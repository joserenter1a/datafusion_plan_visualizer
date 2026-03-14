"""Tests for engine.context — registration, deregistration, validation, bootstrap."""

import pathlib

import pandas
import pytest

from engine.context import (
    _validate_csv,
    deregister_table,
    register_csv,
    register_json,
)

# ── _validate_csv ─────────────────────────────────────────────────────────────


class TestValidateCsv:
    def test_valid_csv_passes(self, valid_csv: pathlib.Path) -> None:
        _validate_csv(valid_csv)  # must not raise

    def test_empty_file_raises(self, csv_empty: pathlib.Path) -> None:
        with pytest.raises(ValueError, match="empty"):
            _validate_csv(csv_empty)

    def test_blank_header_raises(self, csv_blank_header: pathlib.Path) -> None:
        with pytest.raises(ValueError, match="whitespace-only"):
            _validate_csv(csv_blank_header)

    def test_duplicate_header_raises(self, csv_duplicate_headers: pathlib.Path) -> None:
        with pytest.raises(ValueError, match="Duplicate"):
            _validate_csv(csv_duplicate_headers)

    def test_whitespace_collision_raises(
        self, csv_whitespace_collision: pathlib.Path
    ) -> None:
        with pytest.raises(ValueError, match="ambiguous"):
            _validate_csv(csv_whitespace_collision)

    def test_unserializable_type_raises(self, tmp_path: pathlib.Path) -> None:
        """A column with complex128 dtype cannot be converted to Parquet."""
        import unittest.mock as mock

        import numpy as np

        p = tmp_path / "complex.csv"
        p.write_text("x\n1+2j\n3+4j\n")

        # Build a DataFrame whose 'x' column is genuinely complex128 and
        # inject it as the return value of the sample read inside _validate_csv.
        complex_df = pandas.DataFrame({"x": np.array([1 + 2j, 3 + 4j])})
        with mock.patch("engine.context.pandas.read_csv", return_value=complex_df):
            with pytest.raises(ValueError, match="cannot"):
                _validate_csv(p)


# ── register_csv ──────────────────────────────────────────────────────────────


class TestRegisterCsv:
    def test_registers_table(
        self,
        valid_csv: pathlib.Path,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """register_csv converts the CSV to Parquet and registers in context."""
        import engine.context as ctx_mod

        # Point DATA_DIR at tmp_path so we don't touch the real data directory
        monkeypatch.setattr(ctx_mod, "_DATA_DIR", tmp_path)
        # Use a fresh context so tests are isolated
        fresh = __import__("datafusion").SessionContext()
        monkeypatch.setattr(ctx_mod, "context", fresh)

        name = register_csv(valid_csv, "valid_test")

        assert name == "valid_test"
        assert (tmp_path / "valid_test.parquet").exists()
        tables = fresh.catalog("datafusion").schema("public").table_names()
        assert "valid_test" in tables

    def test_rejects_invalid_csv(
        self,
        csv_duplicate_headers: pathlib.Path,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """register_csv raises before writing any file when validation fails."""
        import engine.context as ctx_mod

        monkeypatch.setattr(ctx_mod, "_DATA_DIR", tmp_path)

        with pytest.raises(ValueError, match="Duplicate"):
            register_csv(csv_duplicate_headers, "bad")

        # No parquet file should have been written
        assert not (tmp_path / "bad.parquet").exists()

    def test_idempotent_reupload(
        self,
        valid_csv: pathlib.Path,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Re-registering the same name replaces the existing table."""
        import engine.context as ctx_mod

        fresh = __import__("datafusion").SessionContext()
        monkeypatch.setattr(ctx_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(ctx_mod, "context", fresh)

        register_csv(valid_csv, "t")
        register_csv(valid_csv, "t")  # second call must not raise

        tables = fresh.catalog("datafusion").schema("public").table_names()
        assert "t" in tables
        assert len(tables) == 1


# ── register_json ─────────────────────────────────────────────────────────────


class TestRegisterJson:
    def test_registers_ndjson(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import engine.context as ctx_mod

        fresh = __import__("datafusion").SessionContext()
        monkeypatch.setattr(ctx_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(ctx_mod, "context", fresh)

        ndjson = tmp_path / "src" / "events.json"
        ndjson.parent.mkdir()
        ndjson.write_text('{"id": 1, "event": "click"}\n{"id": 2, "event": "hover"}\n')

        name = register_json(ndjson, "events")

        assert name == "events"
        assert (tmp_path / "events.json").exists()
        assert "events" in fresh.catalog("datafusion").schema("public").table_names()


# ── deregister_table ──────────────────────────────────────────────────────────


class TestDeregisterTable:
    def test_removes_table_and_file(
        self,
        valid_csv: pathlib.Path,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import engine.context as ctx_mod

        fresh = __import__("datafusion").SessionContext()
        monkeypatch.setattr(ctx_mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(ctx_mod, "context", fresh)

        register_csv(valid_csv, "gone")
        assert (tmp_path / "gone.parquet").exists()

        deregister_table("gone")

        assert not (tmp_path / "gone.parquet").exists()
        assert "gone" not in fresh.catalog("datafusion").schema("public").table_names()

    def test_raises_for_unknown_table(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import engine.context as ctx_mod

        fresh = __import__("datafusion").SessionContext()
        monkeypatch.setattr(ctx_mod, "context", fresh)

        with pytest.raises(KeyError, match="no_such_table"):
            deregister_table("no_such_table")
