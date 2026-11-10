"""0.11.6: the documents say how many words a search uses.

Field run on 0.11.5 (2026-11-10). /kg-query looked for the source's hypothesis codes with
`query_graph(text="h1 h2 … h20")`, and the engine searched on the first 12 (`_QUERY_TERM_CAP`), as its
`query_terms` showed. The answer did not suffer: it reached H16 through other edges. But neither /kg-query
nor the tool reference said that a search has a word limit, so the model could not plan for it.

These tests tie the stated limit to the constant, so the text cannot drift from the engine.
"""
from __future__ import annotations

from pathlib import Path

from kg_engine.projector import _QUERY_TERM_CAP, DerivedReader
from kg_engine.server import _register

REPO = Path(__file__).resolve().parents[1]
QUERY_MD = (REPO / "commands" / "kg-query.md").read_text(encoding="utf-8")
TOOLS_MD = (REPO / "skills" / "burgess" / "references" / "tools.md").read_text(encoding="utf-8")
ARCH_MD = (REPO / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")


def test_the_field_search_keeps_the_first_twelve_codes():
    codes = " ".join(f"h{i}" for i in range(1, 21))
    assert DerivedReader._query_terms(codes) == [f"h{i}" for i in range(1, _QUERY_TERM_CAP + 1)]


def test_kg_query_states_the_limit_and_what_to_do_about_it():
    assert f"at most {_QUERY_TERM_CAP} words" in QUERY_MD
    assert f"The same limit of {_QUERY_TERM_CAP} words applies" in QUERY_MD
    assert "several searches" in QUERY_MD and "query_terms" in QUERY_MD


def test_the_tool_reference_and_the_architecture_state_the_limit():
    assert f"Only the first {_QUERY_TERM_CAP} search words count" in TOOLS_MD
    assert f"at most the first {_QUERY_TERM_CAP} of the query" in TOOLS_MD
    assert f"Only the first {_QUERY_TERM_CAP} count (`_QUERY_TERM_CAP`" in ARCH_MD


class _FakeMCP:
    def __init__(self):
        self.tools: dict = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def test_the_tool_descriptions_state_the_limit(engine):
    mcp = _FakeMCP()
    _register(mcp, engine)
    for name in ("kg_context", "query_graph"):
        doc = " ".join((mcp.tools[name].__doc__ or "").split())
        assert f"the first {_QUERY_TERM_CAP}" in doc and "dropped" in doc, name
