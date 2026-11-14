"""MCP server exposing ``search_trials`` and ``build_evidence`` as tools.

Run with ``ctgov-evidence-mcp`` (stdio transport). Needs the ``mcp`` extra.
"""

from __future__ import annotations

from .models import Query
from .pipeline import build_evidence as _build_evidence
from .summarise import phase_label, table_rows


def search_trials(
    condition: str | None = None,
    intervention: str | None = None,
    phase: list[str] | None = None,
    status: list[str] | None = None,
    max_studies: int = 25,
) -> dict:
    """Search ClinicalTrials.gov and return one compact row per trial."""
    ev = _build_evidence(
        Query(
            condition=condition,
            intervention=intervention,
            phase=phase or [],
            status=status or [],
            max_studies=max_studies,
        )
    )
    return {
        "total_found": ev.total_found,
        "returned": len(ev.trials),
        "truncated": ev.truncated,
        "trials": table_rows(ev.trials),
    }


def build_evidence(
    condition: str | None = None,
    intervention: str | None = None,
    phase: list[str] | None = None,
    status: list[str] | None = None,
    nct_ids: list[str] | None = None,
    max_studies: int = 100,
) -> dict:
    """Build the full evidence object: normalised trials with source paths, and the summary."""
    ev = _build_evidence(
        Query(
            condition=condition,
            intervention=intervention,
            phase=phase or [],
            status=status or [],
            nct_ids=nct_ids or [],
            max_studies=max_studies,
        )
    )
    data = ev.model_dump(mode="json")
    data["phase_labels"] = {t.nct_id: phase_label(t.phase.value) for t in ev.trials}
    return data


def main() -> None:
    server = make_server()
    server.run()


def make_server():
    """Return the MCP server with both tools registered (works with mcp 1.x and 2.x)."""
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp 2.x
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP as Server  # mcp 1.x
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "The mcp package is not installed; run pip install 'ctgov-evidence[mcp]'"
            ) from exc
    server = Server("ctgov-evidence")
    server.tool()(search_trials)
    server.tool()(build_evidence)
    return server


if __name__ == "__main__":  # pragma: no cover
    main()
