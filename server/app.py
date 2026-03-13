"""FastAPI application factory for the DataFusion Plan Visualizer."""

import asyncio
import pathlib
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from engine import bootstrap
from .routes import router

_STATIC_DIR: pathlib.Path = pathlib.Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan handler.

    Runs :func:`~engine.bootstrap` on startup so that missing data directories
    or corrupt Parquet files raise immediately — with a clear traceback in the
    server log — rather than failing silently inside a module import.
    """
    await asyncio.to_thread(bootstrap)
    yield


app = FastAPI(
    title="DataFusion Plan Visualizer",
    description="Interactively visualize Apache DataFusion logical query plans.",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
app.include_router(router)
