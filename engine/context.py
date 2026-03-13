"""Session context management and table registration for DataFusion."""

import csv
import io
import pathlib
import shutil
from typing import TypedDict

import datafusion
import pandas


_DATA_DIR: pathlib.Path = pathlib.Path(__file__).parent.parent / "data"

context: datafusion.SessionContext = datafusion.SessionContext()


class ColumnInfo(TypedDict):
    """Schema information for a single column."""

    name: str
    type: str
    nullable: bool


class TableInfo(TypedDict):
    """Name and column schema for a registered table."""

    name: str
    columns: list[ColumnInfo]


_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".csv", ".json", ".avro"})

_SAMPLE_ROWS: int = 500


def _validate_csv(path: pathlib.Path) -> None:
    """Validate a CSV file's headers and column types before writing to disk.

    Reads only the header row for structural checks, then reads a sample of
    up to :data:`_SAMPLE_ROWS` rows and attempts an in-memory Parquet
    round-trip to catch type incompatibilities — all before any file is
    written to ``_DATA_DIR``.

    Args:
        path: Path to the CSV file to validate.

    Raises:
        ValueError: If the file is empty, has empty or whitespace-only column
            names, has duplicate column names (exact or after stripping
            whitespace), or contains a column whose inferred type cannot be
            serialised to Parquet by PyArrow.
    """
    # ── 1. Read raw headers without pandas (preserves original names) ──────
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        try:
            raw_headers: list[str] = next(reader)
        except StopIteration:
            raise ValueError("CSV file is empty — no header row found.")

    if not raw_headers:
        raise ValueError("CSV file has no columns.")

    # ── 2. Reject empty / whitespace-only names ────────────────────────────
    blank_positions: list[int] = [
        i + 1 for i, h in enumerate(raw_headers) if not h.strip()
    ]
    if blank_positions:
        positions_str = ", ".join(str(p) for p in blank_positions)
        raise ValueError(
            f"Empty or whitespace-only column name(s) at position(s): {positions_str}. "
            "All columns must have a non-blank name."
        )

    # ── 3. Reject exact duplicates ─────────────────────────────────────────
    seen_exact: dict[str, int] = {}
    for i, h in enumerate(raw_headers):
        if h in seen_exact:
            raise ValueError(
                f"Duplicate column name '{h}' at positions "
                f"{seen_exact[h] + 1} and {i + 1}."
            )
        seen_exact[h] = i

    # ── 4. Reject names that collide after stripping whitespace ────────────
    seen_stripped: dict[str, int] = {}
    for i, h in enumerate(raw_headers):
        stripped = h.strip()
        if stripped in seen_stripped:
            raise ValueError(
                f"Column names at positions {seen_stripped[stripped] + 1} and "
                f"{i + 1} are ambiguous: '{raw_headers[seen_stripped[stripped]]}' "
                f"and '{h}' are identical after stripping whitespace."
            )
        seen_stripped[stripped] = i

    # ── 5. Sample read + in-memory Parquet round-trip ─────────────────────
    try:
        sample: pandas.DataFrame = pandas.read_csv(path, nrows=_SAMPLE_ROWS)
    except Exception as exc:
        raise ValueError(f"Could not parse CSV: {exc}") from exc

    buf = io.BytesIO()
    try:
        sample.to_parquet(buf)
    except Exception:
        # Identify the offending column(s) for a clear error message.
        bad: list[str] = []
        for col in sample.columns:
            try:
                sample[[col]].to_parquet(io.BytesIO())
            except Exception:
                bad.append(f"'{col}' ({sample[col].dtype})")
        if bad:
            raise ValueError(
                f"Column(s) with types that DataFusion cannot handle: "
                f"{', '.join(bad)}. "
                "Consider casting these columns before uploading."
            )
        # Fallback if per-column scan didn't isolate it (e.g. interaction bug).
        raise ValueError(
            "CSV contains column types that cannot be converted to Parquet. "
            "Check for complex numbers, mixed-type columns, or unsupported dtypes."
        )


def _evict(name: str) -> None:
    """Deregister *name* from the context if it exists (ignores missing)."""
    try:
        context.deregister_table(name)
    except Exception:
        pass


def register_csv(csv_path: pathlib.Path, table_name: str | None = None) -> str:
    """Convert a CSV file to Parquet and register it in the session context.

    If a table with the same name already exists it is deregistered first,
    making this function idempotent for re-uploads.

    Args:
        csv_path: Path to the source CSV file.
        table_name: Name to register the table under. Defaults to the
            CSV stem (filename without extension).

    Returns:
        The name under which the table was registered.
    """
    name: str = table_name or csv_path.stem
    _validate_csv(csv_path)
    parquet_path: pathlib.Path = _DATA_DIR / f"{name}.parquet"
    pandas.read_csv(csv_path).to_parquet(parquet_path)
    _evict(name)
    context.register_parquet(name, parquet_path)
    return name


def register_json(json_path: pathlib.Path, table_name: str | None = None) -> str:
    """Copy a newline-delimited JSON file to the data directory and register it.

    DataFusion expects one JSON object per line (newline-delimited JSON / NDJSON).
    The file is copied to ``_DATA_DIR`` so that it persists across server restarts.

    If a table with the same name already exists it is deregistered first,
    making this function idempotent for re-uploads.

    Args:
        json_path: Path to the source NDJSON file.
        table_name: Name to register the table under. Defaults to the
            file stem (filename without extension).

    Returns:
        The name under which the table was registered.
    """
    name: str = table_name or json_path.stem
    dest: pathlib.Path = _DATA_DIR / f"{name}.json"
    shutil.copy2(json_path, dest)
    _evict(name)
    context.register_json(name, dest)
    return name


def register_avro(avro_path: pathlib.Path, table_name: str | None = None) -> str:
    """Copy an Avro file to the data directory and register it.

    The file is copied to ``_DATA_DIR`` so that it persists across server
    restarts.  If a table with the same name already exists it is deregistered
    first, making this function idempotent for re-uploads.

    Args:
        avro_path: Path to the source Avro file.
        table_name: Name to register the table under. Defaults to the
            file stem (filename without extension).

    Returns:
        The name under which the table was registered.
    """
    name: str = table_name or avro_path.stem
    dest: pathlib.Path = _DATA_DIR / f"{name}.avro"
    shutil.copy2(avro_path, dest)
    _evict(name)
    context.register_avro(name, dest)
    return name


def deregister_table(name: str) -> None:
    """Deregister a table from the session context and delete its backing file.

    Removes whichever of ``.parquet``, ``.json``, or ``.avro`` is present in
    ``_DATA_DIR`` for *name*.

    Args:
        name: The registered table name to remove.

    Raises:
        KeyError: If no table with *name* is currently registered.
    """
    schema_provider = context.catalog("datafusion").schema("public")
    if name not in schema_provider.table_names():
        raise KeyError(f"Table '{name}' is not registered")
    context.deregister_table(name)
    for ext in (".parquet", ".json", ".avro"):
        (_DATA_DIR / f"{name}{ext}").unlink(missing_ok=True)


def get_tables() -> list[TableInfo]:
    """Return schema information for every table registered in the session.

    Reads directly from the DataFusion catalog so the result is always
    current, even after dynamic registration.

    Returns:
        A list of :class:`TableInfo` dicts sorted by table name, each
        containing the table name and a list of :class:`ColumnInfo` dicts
        describing each column's name, Arrow type string, and nullability.
    """
    schema_provider = context.catalog("datafusion").schema("public")
    result: list[TableInfo] = []
    for name in sorted(schema_provider.table_names()):
        table = schema_provider.table(name)
        columns: list[ColumnInfo] = [
            ColumnInfo(name=f.name, type=str(f.type), nullable=f.nullable)
            for f in table.schema
        ]
        result.append(TableInfo(name=name, columns=columns))
    return result


def bootstrap() -> None:
    """Register all tables found in the data directory on startup.

    Converts the bundled ``recipe_table.csv`` to Parquet if it has not been
    converted yet, then registers every ``*.parquet`` file present in
    ``_DATA_DIR``.  This makes all previously uploaded tables survive a
    hot-reload or server restart without requiring the user to re-upload them.

    This function is intentionally **not** called at import time.  It is
    invoked from the FastAPI lifespan handler so that startup errors surface
    immediately in the server log rather than being raised inside a module
    import and potentially swallowed or attributed to the wrong call site.

    Raises:
        FileNotFoundError: If ``_DATA_DIR`` does not exist, or if the default
            ``recipe_table.csv`` is absent and its Parquet cache has not yet
            been created.
    """
    if not _DATA_DIR.exists():
        raise FileNotFoundError(
            f"Data directory not found: {_DATA_DIR}. "
            "Create the directory and add a recipe_table.csv file to get started."
        )

    default_parquet = _DATA_DIR / "recipe_table.parquet"
    if not default_parquet.exists():
        default_csv = _DATA_DIR / "recipe_table.csv"
        if not default_csv.exists():
            raise FileNotFoundError(
                f"Default table not found: {default_csv}. "
                "Add a recipe_table.csv to the data directory or place a "
                "pre-converted recipe_table.parquet there instead."
            )
        pandas.read_csv(default_csv).to_parquet(default_parquet)

    for parquet_file in sorted(_DATA_DIR.glob("*.parquet")):
        try:
            context.register_parquet(parquet_file.stem, parquet_file)
        except Exception:
            pass

    for json_file in sorted(_DATA_DIR.glob("*.json")):
        try:
            context.register_json(json_file.stem, json_file)
        except Exception:
            pass

    for avro_file in sorted(_DATA_DIR.glob("*.avro")):
        try:
            context.register_avro(avro_file.stem, avro_file)
        except Exception:
            pass
