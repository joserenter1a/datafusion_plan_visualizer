"""HTTP route handlers for the DataFusion Plan Visualizer API."""

import asyncio
import pathlib
import shutil
import tempfile
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from engine.context import (
    _SUPPORTED_EXTENSIONS,
    TableInfo,
    deregister_table,
    get_tables,
    register_avro,
    register_csv,
    register_json,
)
from engine.plan import (
    diff_logical_plans,
    physical_plan,
    physical_plan_to_cytoscape,
    plan,
    plan_to_cytoscape,
)
from engine.query import query

_STATIC_DIR: pathlib.Path = pathlib.Path(__file__).parent.parent / "static"

router = APIRouter()

PlanType = Literal["logical", "optimized", "physical", "diff"]


class PlanRequest(BaseModel):
    """Request body for ``POST /plan``."""

    sql: str
    """A valid SQL query string referencing registered tables."""

    plan_type: PlanType = "logical"
    """Which plan representation to return.

    - ``"logical"``   — unoptimized logical plan
    - ``"optimized"`` — optimizer-rewritten logical plan
    - ``"physical"``  — physical execution plan (``ExecutionPlan``)
    - ``"diff"``      — side-by-side diff of unoptimized vs optimized
    """


_ALLOWED_STMT_KEYWORDS: frozenset[str] = frozenset({"SELECT", "WITH", "EXPLAIN"})


def _assert_select_only(statement: str) -> None:
    """Reject SQL that is not a plain SELECT, WITH (CTE), or EXPLAIN statement.

    Prevents DDL (``DROP``, ``CREATE``, ``ALTER``) and DML (``INSERT``,
    ``UPDATE``, ``DELETE``) statements from reaching the DataFusion session,
    and blocks statement-stacking attacks (e.g. ``SELECT 1; DROP TABLE …``).

    Args:
        statement: Raw SQL string from the request.

    Raises:
        ValueError: If the statement is empty, starts with a disallowed
            keyword, or contains multiple statements separated by a
            semicolon.
    """
    stripped = statement.strip()
    if not stripped:
        raise ValueError("SQL statement is empty.")

    first_keyword = stripped.split()[0].upper().rstrip(";")
    if first_keyword not in _ALLOWED_STMT_KEYWORDS:
        raise ValueError(
            f"Only SELECT statements are permitted. "
            f"Statement starting with '{first_keyword}' is not allowed."
        )

    # Prevent statement stacking: reject any semicolons except a trailing one.
    if ";" in stripped.rstrip(";"):
        raise ValueError(
            "Multiple statements are not permitted. "
            "Submit one SELECT statement at a time."
        )


def _build_plan_response(sql: str, plan_type: PlanType) -> dict[str, Any]:
    """Execute *sql* and build the plan response for the requested *plan_type*.

    Runs entirely synchronously so it can be safely offloaded to a thread
    via :func:`asyncio.to_thread`.

    Args:
        sql:       SQL query string to execute.
        plan_type: One of ``"logical"``, ``"optimized"``, ``"physical"``,
                   or ``"diff"``.

    Returns:
        For single-plan types::

            {"type": "single", "elements": [...]}

        For diff::

            {"type": "diff", "left": [...], "right": [...]}

    Raises:
        ValueError: If *sql* is not a permitted SELECT statement.
    """
    _assert_select_only(sql)
    df = query(sql)

    if plan_type == "logical":
        return {
            "type": "single",
            "elements": plan_to_cytoscape(plan(df, optimized=False)),
        }

    if plan_type == "optimized":
        return {
            "type": "single",
            "elements": plan_to_cytoscape(plan(df, optimized=True)),
        }

    if plan_type == "physical":
        return {
            "type": "single",
            "elements": physical_plan_to_cytoscape(physical_plan(df)),
        }

    # plan_type == "diff"
    left, right = diff_logical_plans(
        plan(df, optimized=False), plan(df, optimized=True)
    )
    return {"type": "diff", "left": left, "right": right}


@router.get("/")
def index() -> FileResponse:
    """Serve the single-page application HTML entry point."""
    return FileResponse(_STATIC_DIR / "index.html")


@router.get("/tables")
def list_tables() -> dict[str, list[TableInfo]]:
    """Return all tables registered in the current session with their schemas.

    Returns:
        A JSON object with a single ``"tables"`` key whose value is a list
        of :class:`~engine.context.TableInfo` objects.
    """
    return {"tables": get_tables()}


_REGISTER_FN = {
    ".csv": register_csv,
    ".json": register_json,
    ".avro": register_avro,
}


@router.post("/tables")
async def upload_table(file: UploadFile = File(...)) -> dict[str, Any]:
    """Register a new table from an uploaded CSV, JSON, or Avro file.

    The file is written to a temporary path, then the appropriate registration
    function is offloaded to a thread.  If a table with that name already
    exists it is replaced.

    Supported formats:

    - ``.csv``  — converted to Parquet then registered
    - ``.json`` — newline-delimited JSON (NDJSON), registered directly
    - ``.avro`` — Apache Avro, registered directly

    Args:
        file: The multipart-uploaded data file.

    Returns:
        A JSON object containing the full updated ``"tables"`` list and the
        ``"registered"`` name of the newly added table.

    Raises:
        HTTPException: 400 if the file extension is unsupported or
            registration fails.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext: str = pathlib.Path(file.filename).suffix.lower()
    if ext not in _REGISTER_FN:
        supported = ", ".join(sorted(_SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {supported}",
        )

    table_name: str = pathlib.Path(file.filename).stem

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = pathlib.Path(tmp.name)

    try:
        name: str = await asyncio.to_thread(_REGISTER_FN[ext], tmp_path, table_name)
        return {"tables": get_tables(), "registered": name}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        tmp_path.unlink(missing_ok=True)


@router.delete("/tables/{name}")
async def delete_table(name: str) -> dict[str, Any]:
    """Deregister a table and delete its backing Parquet file.

    Args:
        name: The registered table name to remove.

    Returns:
        A JSON object containing the updated ``"tables"`` list.

    Raises:
        HTTPException: 404 if no table with *name* is registered.
    """
    try:
        await asyncio.to_thread(deregister_table, name)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"tables": get_tables()}


@router.post("/plan")
async def get_plan(req: PlanRequest) -> dict[str, Any]:
    """Execute a SQL query and return the requested plan as Cytoscape.js elements.

    The synchronous planning chain is offloaded to a thread so the event loop
    remains free to handle other requests.

    Args:
        req: Request body with ``sql`` and ``plan_type`` fields.

    Returns:
        For ``"logical"``, ``"optimized"``, or ``"physical"``::

            {"type": "single", "elements": [...]}

        For ``"diff"``::

            {"type": "diff", "left": [...], "right": [...]}

    Raises:
        HTTPException: 400 if the SQL is invalid or planning fails.
    """
    try:
        return await asyncio.to_thread(_build_plan_response, req.sql, req.plan_type)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
