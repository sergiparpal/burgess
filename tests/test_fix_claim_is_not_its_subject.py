"""0.14.5: a claim about a concept is not that concept, and a lead's new end is never its other end.

Field report on 0.14.4 (2026-11-13).

- A grounder rejected `agente attacked_by agentes-multiplican-errores` as wrong-node. The span was «el producto
  hecho al 100% por agentes suele ser deficiente: los agentes multiplican los errores», and its lead named a new
  head, `producto-hecho-al-100-por-agentes`: the product.
- The leads extractor looked in known_nodes for the same concept under another id, as its contract said, and
  took the claim node `producto-100-por-agentes-deficiente` («El producto hecho al 100 % por agentes suele ser
  deficiente») for the product.
- Its edge `producto-100-por-agentes-deficiente attacked_by agentes-multiplican-errores` turned the claim's own
  reason into an attack on it. The next grounder rejected it as wrong-relation.
- That pass left a lead whose new head is that same product and whose TAIL is that same claim:
  `producto-hecho-al-100-por-agentes attacked_by producto-100-por-agentes-deficiente`. The same mistake there
  makes a self-loop, which kg_write rejects. The contract said a self-loop has no claim to repair and to drop
  it, so the lead would have stayed pending and failed the same way on every run.

The contract now says that a claim about a concept is not that concept, and that a lead's new end is never its
other end. In leads mode, a self-loop means re-sending with the lead's own id. The build brief says so too.
"""
from __future__ import annotations

from pathlib import Path

from kg_engine.model import edge_id
from kg_engine.server import KGEngine

REPO = Path(__file__).resolve().parents[1]
PACK = REPO / "pack" / "pack.yaml"
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
CMD = (REPO / "commands" / "kg-build.md").read_text(encoding="utf-8")
SPAN = "el producto hecho al 100% por agentes suele ser deficiente: los agentes multiplican los errores"
DOC = f"## Críticas\nSegún Zechner, {SPAN}.\n"
CLAIM = "producto-100-por-agentes-deficiente"
PRODUCT = "producto-hecho-al-100-por-agentes"
REJECTED = edge_id("factoria-agentica", "attacked_by", CLAIM)


def _flat(text: str) -> str:
    return " ".join(text.split())


# ---- the premise: the trap the contract closes is real in the engine -----------------------------------

def _engine_with_the_lead(vault: Path, tmp_path: Path) -> KGEngine:
    src = tmp_path / "s.md"
    src.write_text(DOC, encoding="utf-8")
    eng = KGEngine(vault, source_path=src, pack_path=PACK)
    nodes = [{"id": "factoria-agentica", "label": "Factoría agéntica", "node_type": "primitive",
              "body": "Agentes en segundo plano."},
             {"id": CLAIM, "label": "El producto hecho al 100 % por agentes suele ser deficiente",
              "node_type": "claim", "body": "Zechner: el producto hecho solo por agentes suele ser deficiente."}]
    edge = {"source": "factoria-agentica", "target": CLAIM, "relation": "attacked_by", "span": SPAN,
            "source_file": "s.md"}
    assert eng.kg_write({"nodes": nodes, "edges": [edge]})["dispositions"]["ACCEPTED"] == 3
    out = eng.kg_ground(REJECTED, "rejected", note="wrong-node: the critique targets the product, not the factory",
                        lead=f"{PRODUCT} attacked_by {CLAIM}")
    assert out["ok"], out
    assert eng.kg_ground_plan("", "")["queue"]["leads_pending"] == 1
    return eng


def _write_lead(eng: KGEngine, head: str, nodes: list) -> dict:
    edge = {"source": head, "target": CLAIM, "relation": "attacked_by", "span": SPAN, "source_file": "s.md",
            "notes": f"lead (from {REJECTED})"}
    return eng.kg_write({"nodes": nodes, "edges": [edge]})


def test_the_claim_put_on_the_new_end_is_a_self_loop_and_the_lead_stays(vault, tmp_path):
    eng = _engine_with_the_lead(vault, tmp_path)
    out = _write_lead(eng, CLAIM, [])                      # the field mistake: the claim taken for the product
    reasons = [d["reason"] for d in out["details"] if d["kind"] == "edge"]
    assert out["dispositions"]["REJECTED"] == 1 and "self-loop" in reasons[0], out
    assert eng.kg_ground_plan("", "")["queue"]["leads_pending"] == 1     # nothing taken: it would come back


def test_the_lead_written_with_its_own_new_end_lands_and_is_taken(vault, tmp_path):
    eng = _engine_with_the_lead(vault, tmp_path)
    product = {"id": PRODUCT, "label": "El producto hecho al 100 % por agentes", "node_type": "primitive",
               "body": "Software hecho por completo por agentes."}
    out = _write_lead(eng, PRODUCT, [product])
    assert out["dispositions"]["ACCEPTED"] == 2, out
    assert eng.kg_ground_plan("", "")["queue"]["leads_pending"] == 0


# ---- the texts -------------------------------------------------------------------------------------

def test_the_contract_says_a_claim_about_a_concept_is_not_that_concept():
    known = _flat(EXTRACTOR.split("**`kg_section` also returns `known_nodes`**", 1)[1].split("\n\nEither way", 1)[0])
    assert "**A claim about a concept is not that concept.**" in known
    assert "Use a claim's id only when your edge's end is that whole statement." in known


def test_a_leads_new_end_is_never_its_other_end_nor_a_claim_about_it():
    leads = _flat(EXTRACTOR.split("## Leads mode", 1)[1].split("\n## ", 1)[0])
    assert "**Never the lead's other end.** A known id that would make the head and the tail one node" in leads
    assert "**Never a claim about the end**" in leads


def test_a_self_loop_in_leads_mode_is_re_sent_with_the_leads_own_id():
    procedure = _flat(EXTRACTOR.split("## Procedure", 1)[1].split("\n## ", 1)[0])
    assert ("In leads mode it means a known id you put on a new end made the lead's two ends one node: declare "
            "the lead's own id for that end and re-send.") in procedure
    assert "There is no claim to repair: drop it." in procedure          # the build-mode rule stands


def test_the_leads_brief_carries_the_rule():
    leads_brief = _flat(CMD.split("## Leads mode", 1)[1])
    assert ("declare a new end in nodes[] unless known_nodes holds the same concept: never the lead's other end, "
            "and never a claim about the end.") in leads_brief
