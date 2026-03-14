"""SQL query execution against the shared DataFusion session context."""

import datafusion

from . import context as ctx_mod


def query(statement: str) -> datafusion.DataFrame:
    """Execute a SQL statement and return the resulting lazy DataFrame.

    The query is parsed and validated immediately but not executed until
    the caller collects or displays the DataFrame.

    Args:
        statement: A valid SQL query string referencing registered tables.

    Returns:
        A lazy :class:`datafusion.DataFrame` representing the query result.
    """
    return ctx_mod.context.sql(statement)
