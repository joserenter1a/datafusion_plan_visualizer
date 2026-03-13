# DataFusion Plan Visualizer

An interactive web application for visualizing the logical query plan DAG produced by [Apache DataFusion](https://datafusion.apache.org/). Write SQL against uploaded CSV tables and inspect how DataFusion's query planner decomposes it into a tree of relational operators — both before and after the optimizer runs.

![Plan Visualizer](docs/assets/visualizer.png)

---

## Features

- **Interactive DAG** — Cytoscape.js renders the plan as a navigable, zoomable graph
- **Unoptimized vs optimized plans** — toggle between the raw parser output and the optimizer-rewritten plan with a single checkbox
- **Color-coded operators** — each node type (TableScan, Filter, Projection, Aggregate, Sort, Limit, Join) has a distinct color
- **Live table registry** — sidebar shows every registered table with its full Arrow schema
- **CSV drag-and-drop** — drop any CSV file onto the sidebar to convert it to Parquet, register it in the session, and query it immediately; re-uploading a file with the same name replaces the existing table

---

## Technologies

| Layer | Technology | Role |
|---|---|---|
| Query engine | [Apache DataFusion](https://datafusion.apache.org/) | SQL parsing, logical planning, optimization |
| Columnar format | [Apache Parquet](https://parquet.apache.org/) via [PyArrow](https://arrow.apache.org/docs/python/) | On-disk table storage |
| Data wrangling | [pandas](https://pandas.pydata.org/) | CSV ingestion and Parquet conversion |
| API server | [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) | Async HTTP layer, file upload handling |
| Graph rendering | [Cytoscape.js](https://js.cytoscape.org/) | DAG layout and interactive visualization |
| Package manager | [uv](https://docs.astral.sh/uv/) | Fast Python dependency and environment management |
| Type checker | [ty](https://github.com/astral-sh/ty) | Static type analysis |

---

## Project Structure

```
exec_plan/
├── engine/                  # DataFusion wrapper library
│   ├── __init__.py          # Public API re-exports
│   ├── context.py           # Session context, CSV registration, catalog queries
│   ├── query.py             # SQL execution
│   └── plan.py              # Plan extraction and Cytoscape.js serialization
├── server/                  # FastAPI web server
│   ├── app.py               # Application factory, static file mount
│   └── routes.py            # Route handlers: GET /, GET /tables, POST /tables, POST /plan
├── static/                  # Front-end assets
│   ├── index.html           # Markup and styles
│   └── js/
│       └── main.js          # Cytoscape setup, plan fetching, table sidebar, CSV upload
├── data/                    # CSV source files and generated Parquet files
│   └── recipe_table.csv
└── pyproject.toml
```

---

## Architecture

```
Browser
  │  GET /           → index.html
  │  GET /tables     → [{name, columns[]}]
  │  POST /tables    → CSV upload → [{name, columns[]}]
  │  POST /plan      → {sql, optimized} → {elements[]}
  ▼
FastAPI (server/app.py)
  │
  ├── routes.py
  │     ├── list_tables()    → engine.get_tables()
  │     ├── upload_table()   → engine.register_csv()
  │     └── get_plan()       → engine.query() → engine.plan() → engine.plan_to_cytoscape()
  │
  └── engine/
        ├── context.py       # Singleton SessionContext; register_csv + get_tables
        ├── query.py         # context.sql(statement) → DataFrame
        └── plan.py          # df.logical_plan() / df.optimized_logical_plan()
                             # → depth-first traversal → Cytoscape node/edge list
```

**Data flow for a plan request:**

1. Browser sends `POST /plan` with `{"sql": "SELECT …", "optimized": false}`
2. `routes.get_plan` calls `engine.query(sql)` → DataFusion returns a lazy `DataFrame`
3. `engine.plan(df)` calls `df.logical_plan()` → `datafusion.LogicalPlan` tree
4. `engine.plan_to_cytoscape(root)` walks the tree via `node.inputs()`, assigns integer IDs, and emits a flat list of node + edge dicts
5. The JSON response is consumed by Cytoscape.js in the browser, which applies a breadth-first hierarchical layout

**Data flow for CSV registration:**

1. Browser sends `POST /tables` with the file as multipart form data
2. `routes.upload_table` writes the upload to a temporary file
3. `engine.register_csv` reads it with pandas, writes Parquet to `data/`, deregisters any existing table with the same name, then calls `context.register_parquet`
4. `engine.get_tables` queries the live DataFusion catalog and returns the updated schema list

---

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (`pip install uv` or see [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/))

---

## Installation

```bash
git clone <repo-url>
cd exec_plan
uv sync
```

---

## Usage

### Start the server

```bash
uv run uvicorn server.app:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

### Query a plan

1. Type a SQL query in the text area (the default table `recipe_table` is pre-registered)
2. Press **Run** or `Cmd/Ctrl + Enter`
3. Toggle **Optimized** to compare the unoptimized plan against the optimizer output

### Register a new table

Drag any CSV file onto the **"Drop CSV to register table"** zone in the sidebar, or click the zone to open a file picker. The table is available for querying immediately after the upload completes.

### API reference

The server also exposes a machine-readable API. Interactive docs are available at [http://localhost:8000/docs](http://localhost:8000/docs).

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | SPA entry point |
| `GET` | `/tables` | List registered tables and schemas |
| `POST` | `/tables` | Register a CSV file as a new table |
| `POST` | `/plan` | Return the logical plan for a SQL query |

---

## Practical Applications

- **Learning SQL internals** — see exactly how a `GROUP BY`, `JOIN`, or subquery is decomposed before execution
- **Query optimization debugging** — compare the unoptimized and optimized plans side-by-side to understand what the optimizer changed (predicate pushdown, projection pruning, etc.)
- **DataFusion development** — inspect custom logical plans or verify that optimizer rules are being applied correctly
- **Education and talks** — a visual alternative to `EXPLAIN` output for teaching relational algebra and query planning concepts

---

## References

- [Apache DataFusion documentation](https://datafusion.apache.org/)
- [DataFusion Python bindings](https://datafusion.apache.org/python/index.html)
- [Cytoscape.js documentation](https://js.cytoscape.org/)
- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [Apache Arrow columnar format](https://arrow.apache.org/docs/format/Columnar.html)
- [Volcano/Iterator model — the foundation of DataFusion's execution model](https://doi.org/10.1145/93605.98720)
- [The Cascades Framework for Query Optimization](https://www.cse.iitb.ac.in/infolab/Data/Courses/CS632/Papers/Cascades-graefe.pdf)
