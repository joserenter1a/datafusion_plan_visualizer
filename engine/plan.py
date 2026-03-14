"""Logical plan extraction, physical plan extraction, and Cytoscape.js serialization."""

import difflib
import re
from typing import Any

import datafusion
from datafusion import LogicalPlan
from datafusion.plan import ExecutionPlan


def plan(df: datafusion.DataFrame, optimized: bool = False) -> LogicalPlan:
    """Extract the logical plan from a DataFrame.

    Args:
        df: The DataFrame whose plan to extract.
        optimized: When ``True`` return the optimizer-rewritten plan.
            When ``False`` (default) return the unoptimized plan as
            produced directly from the SQL parser.

    Returns:
        The :class:`~datafusion.LogicalPlan` for the given DataFrame.
    """
    if optimized:
        return df.optimized_logical_plan()
    return df.logical_plan()


def physical_plan(df: datafusion.DataFrame) -> ExecutionPlan:
    """Extract the physical execution plan from a DataFrame.

    The physical plan reflects the actual runtime operators DataFusion will
    use, including partitioning, parallelism, and file-level push-downs that
    are not visible in the logical plan.

    Args:
        df: The DataFrame whose physical plan to extract.

    Returns:
        The root :class:`~datafusion.plan.ExecutionPlan` node.
    """
    return df.execution_plan()


def _parse_node_schemas(root: LogicalPlan) -> list[list[dict[str, Any]]]:
    """Extract the output schema for every node in the plan tree.

    DataFusion's ``display_graphviz()`` emits a "Detailed LogicalPlan"
    subgraph where each node label has the form::

        "<node label>\\nSchema: [col:Type;N, ...]"

    Nodes appear in the same depth-first pre-order as :func:`plan_to_cytoscape`
    traverses them, so the returned list can be indexed directly by the
    traversal counter.

    Args:
        root: The root :class:`~datafusion.LogicalPlan` to inspect.

    Returns:
        A list of column lists, one per plan node in DFS pre-order.  Each
        column is a dict with ``name``, ``type``, and ``nullable`` keys.
        Returns an empty list if the detailed section cannot be found.
    """
    gv = root.display_graphviz()
    marker = 'graph[label="Detailed LogicalPlan"]'
    idx = gv.find(marker)
    if idx == -1:
        return []

    detailed = gv[idx:]
    schema_strings = re.findall(r'\\nSchema: \[(.*?)\]"', detailed)

    result: list[list[dict[str, Any]]] = []
    for schema_str in schema_strings:
        columns: list[dict[str, Any]] = []
        for col_str in schema_str.split(", "):
            colon = col_str.find(":")
            if colon == -1:
                continue
            name = col_str[:colon]
            rest = col_str[colon + 1 :]
            type_str, _, nullability = rest.partition(";")
            columns.append(
                {
                    "name": name,
                    "type": type_str,
                    "nullable": nullability == "N",
                }
            )
        result.append(columns)
    return result


def plan_to_cytoscape(root: LogicalPlan) -> list[dict[str, Any]]:
    """Serialize a logical plan tree as a flat Cytoscape.js element list.

    Performs a depth-first traversal of the plan tree starting at *root*,
    emitting one node element per plan node and one edge element per
    parent-child relationship.  Each node element includes the output schema
    for that plan step so the frontend can render a detail panel without an
    additional round-trip.

    Node element shape::

        {
            "data": {
                "id":     "<int>",
                "label":  "<display string>",
                "type":   "<node type>",
                "schema": [{"name": "col", "type": "Int64", "nullable": true}, ...]
            }
        }

    Edge element shape::

        {"data": {"source": "<parent id>", "target": "<child id>"}}

    Args:
        root: The root :class:`~datafusion.LogicalPlan` node to serialize.

    Returns:
        A flat list of Cytoscape.js-compatible node and edge dicts ready
        to be passed directly to ``cy.add()``.
    """
    elements: list[dict[str, Any]] = []
    counter: list[int] = [0]
    schemas = _parse_node_schemas(root)

    def traverse(node: LogicalPlan, parent_id: str | None) -> None:
        node_index = counter[0]
        node_id = str(node_index)
        counter[0] += 1
        label: str = node.display()
        node_type: str = label.split(":")[0].strip()
        schema = schemas[node_index] if node_index < len(schemas) else []
        elements.append(
            {
                "data": {
                    "id": node_id,
                    "label": label,
                    "type": node_type,
                    "schema": schema,
                }
            }
        )
        if parent_id is not None:
            elements.append({"data": {"source": parent_id, "target": node_id}})
        for child in node.inputs():
            traverse(child, node_id)

    traverse(root, None)
    return elements


def physical_plan_to_cytoscape(root: ExecutionPlan) -> list[dict[str, Any]]:
    """Serialize a physical execution plan tree as a flat Cytoscape.js element list.

    Mirrors :func:`plan_to_cytoscape` but operates on
    :class:`~datafusion.plan.ExecutionPlan` nodes, which use ``.children()``
    instead of ``.inputs()`` and do not expose a graphviz schema output.
    Schema is therefore always an empty list for physical nodes.

    Args:
        root: The root :class:`~datafusion.plan.ExecutionPlan` node.

    Returns:
        A flat list of Cytoscape.js-compatible node and edge dicts.
    """
    elements: list[dict[str, Any]] = []
    counter: list[int] = [0]

    def traverse(node: ExecutionPlan, parent_id: str | None) -> None:
        node_id = str(counter[0])
        counter[0] += 1
        label: str = node.display().strip()
        node_type: str = label.split(":")[0].strip()
        elements.append(
            {"data": {"id": node_id, "label": label, "type": node_type, "schema": []}}
        )
        if parent_id is not None:
            elements.append({"data": {"source": parent_id, "target": node_id}})
        for child in node.children():
            traverse(child, node_id)

    traverse(root, None)
    return elements


def diff_logical_plans(
    unopt: LogicalPlan, opt: LogicalPlan
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compare an unoptimized and optimized logical plan, annotating each node.

    Serializes both plans to Cytoscape element lists, then uses
    :class:`difflib.SequenceMatcher` on the DFS-ordered node label sequences
    to classify each node as one of:

    - ``"unchanged"`` — same label at a matched position in both plans
    - ``"modified"``  — different label at a matched position (replace opcode)
    - ``"removed"``   — present in the unoptimized plan only
    - ``"added"``     — present in the optimized plan only

    The ``diff`` string is written into each node element's ``data`` dict so
    Cytoscape can apply border styles via data selectors.

    Args:
        unopt: Unoptimized :class:`~datafusion.LogicalPlan`.
        opt:   Optimizer-rewritten :class:`~datafusion.LogicalPlan`.

    Returns:
        A tuple ``(left_elements, right_elements)`` where *left* corresponds
        to the unoptimized plan and *right* to the optimized plan.
    """
    left_elements = plan_to_cytoscape(unopt)
    right_elements = plan_to_cytoscape(opt)

    left_nodes = [e for e in left_elements if "source" not in e["data"]]
    right_nodes = [e for e in right_elements if "source" not in e["data"]]

    left_labels = [n["data"]["label"] for n in left_nodes]
    right_labels = [n["data"]["label"] for n in right_nodes]

    left_status: list[str] = ["removed"] * len(left_nodes)
    right_status: list[str] = ["added"] * len(right_nodes)

    matcher = difflib.SequenceMatcher(None, left_labels, right_labels, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                left_status[i] = "unchanged"
                right_status[j] = "unchanged"
        elif tag == "replace":
            for i in range(i1, i2):
                left_status[i] = "modified"
            for j in range(j1, j2):
                right_status[j] = "modified"

    node_idx = 0
    for e in left_elements:
        if "source" not in e["data"]:
            e["data"]["diff"] = left_status[node_idx]
            node_idx += 1

    node_idx = 0
    for e in right_elements:
        if "source" not in e["data"]:
            e["data"]["diff"] = right_status[node_idx]
            node_idx += 1

    return left_elements, right_elements
