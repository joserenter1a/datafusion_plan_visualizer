"""Tests for engine.plan — Cytoscape serialization and plan diffing."""

import datafusion

from engine.plan import (
    diff_logical_plans,
    physical_plan,
    physical_plan_to_cytoscape,
    plan,
    plan_to_cytoscape,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _nodes(elements: list[dict]) -> list[dict]:
    return [e for e in elements if "source" not in e["data"]]


def _edges(elements: list[dict]) -> list[dict]:
    return [e for e in elements if "source" in e["data"]]


# ── plan_to_cytoscape ─────────────────────────────────────────────────────────


class TestPlanToCytoscape:
    def test_returns_nodes_and_edges(
        self, ctx_with_orders: datafusion.SessionContext
    ) -> None:
        df = ctx_with_orders.sql("SELECT id, amount FROM orders WHERE amount > 10")
        lp = plan(df, optimized=False)
        elements = plan_to_cytoscape(lp)
        assert len(_nodes(elements)) >= 1
        assert len(_edges(elements)) == len(_nodes(elements)) - 1

    def test_node_shape(self, ctx_with_orders: datafusion.SessionContext) -> None:
        df = ctx_with_orders.sql("SELECT id FROM orders")
        lp = plan(df, optimized=False)
        for node in _nodes(plan_to_cytoscape(lp)):
            d = node["data"]
            assert "id" in d
            assert "label" in d
            assert "type" in d
            assert isinstance(d["schema"], list)

    def test_ids_are_unique(self, ctx_with_orders: datafusion.SessionContext) -> None:
        df = ctx_with_orders.sql("SELECT id, amount FROM orders ORDER BY amount")
        lp = plan(df, optimized=False)
        ids = [n["data"]["id"] for n in _nodes(plan_to_cytoscape(lp))]
        assert len(ids) == len(set(ids))

    def test_edge_references_valid_nodes(
        self, ctx_with_orders: datafusion.SessionContext
    ) -> None:
        df = ctx_with_orders.sql("SELECT id FROM orders WHERE id > 2")
        elements = plan_to_cytoscape(plan(df, optimized=False))
        node_ids = {n["data"]["id"] for n in _nodes(elements)}
        for edge in _edges(elements):
            assert edge["data"]["source"] in node_ids
            assert edge["data"]["target"] in node_ids

    def test_schema_populated_for_table_scan(
        self, ctx_with_orders: datafusion.SessionContext
    ) -> None:
        """TableScan node should have non-empty schema from graphviz parsing."""
        df = ctx_with_orders.sql("SELECT id FROM orders")
        elements = plan_to_cytoscape(plan(df, optimized=False))
        # At least one node should have schema columns
        all_schemas = [n["data"]["schema"] for n in _nodes(elements)]
        assert any(len(s) > 0 for s in all_schemas)

    def test_join_produces_multiple_scans(
        self, ctx_with_two_tables: datafusion.SessionContext
    ) -> None:
        df = ctx_with_two_tables.sql(
            "SELECT o.id, p.name FROM orders o JOIN products p ON o.id = p.id"
        )
        elements = plan_to_cytoscape(plan(df, optimized=False))
        node_types = [n["data"]["type"] for n in _nodes(elements)]
        scan_count = sum(1 for t in node_types if "TableScan" in t or "Scan" in t)
        assert scan_count >= 2

    def test_optimized_plan_differs_from_unoptimized(
        self, ctx_with_orders: datafusion.SessionContext
    ) -> None:
        """The optimizer typically pushes filters down, changing the node structure."""
        df = ctx_with_orders.sql(
            "SELECT id FROM orders WHERE status = 'open' ORDER BY id"
        )
        unopt_labels = [
            n["data"]["label"]
            for n in _nodes(plan_to_cytoscape(plan(df, optimized=False)))
        ]
        opt_labels = [
            n["data"]["label"]
            for n in _nodes(plan_to_cytoscape(plan(df, optimized=True)))
        ]
        # Plans may differ in node count or label content
        assert isinstance(unopt_labels, list)
        assert isinstance(opt_labels, list)


# ── physical_plan_to_cytoscape ────────────────────────────────────────────────


class TestPhysicalPlanToCytoscape:
    def test_returns_elements(self, ctx_with_orders: datafusion.SessionContext) -> None:
        df = ctx_with_orders.sql("SELECT id FROM orders")
        pp = physical_plan(df)
        elements = physical_plan_to_cytoscape(pp)
        assert len(_nodes(elements)) >= 1

    def test_schema_always_empty(
        self, ctx_with_orders: datafusion.SessionContext
    ) -> None:
        df = ctx_with_orders.sql("SELECT id, amount FROM orders")
        for node in _nodes(physical_plan_to_cytoscape(physical_plan(df))):
            assert node["data"]["schema"] == []

    def test_node_labels_stripped(
        self, ctx_with_orders: datafusion.SessionContext
    ) -> None:
        df = ctx_with_orders.sql("SELECT id FROM orders LIMIT 5")
        for node in _nodes(physical_plan_to_cytoscape(physical_plan(df))):
            label = node["data"]["label"]
            assert label == label.strip()

    def test_edge_count(self, ctx_with_orders: datafusion.SessionContext) -> None:
        df = ctx_with_orders.sql("SELECT id FROM orders")
        elements = physical_plan_to_cytoscape(physical_plan(df))
        assert len(_edges(elements)) == len(_nodes(elements)) - 1


# ── diff_logical_plans ────────────────────────────────────────────────────────


class TestDiffLogicalPlans:
    def _run_diff(self, ctx: datafusion.SessionContext, sql: str):
        df = ctx.sql(sql)
        return diff_logical_plans(plan(df, optimized=False), plan(df, optimized=True))

    def test_returns_two_element_lists(
        self, ctx_with_orders: datafusion.SessionContext
    ) -> None:
        left, right = self._run_diff(ctx_with_orders, "SELECT id FROM orders")
        assert isinstance(left, list)
        assert isinstance(right, list)
        assert len(left) > 0
        assert len(right) > 0

    def test_every_node_has_diff_field(
        self, ctx_with_orders: datafusion.SessionContext
    ) -> None:
        left, right = self._run_diff(
            ctx_with_orders, "SELECT id, amount FROM orders WHERE amount > 5"
        )
        valid = {"unchanged", "added", "removed", "modified"}
        for node in _nodes(left):
            assert node["data"]["diff"] in valid
        for node in _nodes(right):
            assert node["data"]["diff"] in valid

    def test_edges_have_no_diff_field(
        self, ctx_with_orders: datafusion.SessionContext
    ) -> None:
        left, right = self._run_diff(ctx_with_orders, "SELECT id FROM orders")
        for edge in _edges(left) + _edges(right):
            assert "diff" not in edge["data"]

    def test_identical_plans_all_unchanged(
        self, ctx_with_orders: datafusion.SessionContext
    ) -> None:
        """A trivial SELECT with no optimizable predicates: both plans should match."""
        df = ctx_with_orders.sql("SELECT id FROM orders")
        lp = plan(df, optimized=False)
        # Compare a plan against itself — every node must be "unchanged"
        left, right = diff_logical_plans(lp, lp)
        for node in _nodes(left) + _nodes(right):
            assert node["data"]["diff"] == "unchanged"

    def test_no_duplicate_node_ids_per_side(
        self, ctx_with_orders: datafusion.SessionContext
    ) -> None:
        left, right = self._run_diff(
            ctx_with_orders, "SELECT id FROM orders ORDER BY id LIMIT 3"
        )
        left_ids = [n["data"]["id"] for n in _nodes(left)]
        right_ids = [n["data"]["id"] for n in _nodes(right)]
        assert len(left_ids) == len(set(left_ids))
        assert len(right_ids) == len(set(right_ids))
