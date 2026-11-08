"""0.8.1: the grounder checks what each node names, a counter-edge needs the source's own counter, and
/kg-ground hands its grounders ids, not rules.

Field report on 0.8.0, the second /kg-ground on the Windows corpus:

- Two `defends_against` edges from one document mapped a narrower phrase onto the same broad node: the matrix
  row «Tests protegidos | Manipulación de tests | … | Falla por: Trampas sin tocar tests» and the bullet
  «Resuelve la manipulación de tests visibles», both onto `hacer-trampas-con-los-tests`. Grounders running in
  parallel rejected the first and grounded the second. The extractor's contract has said since 0.6.0 never to
  reuse a node for a broader or narrower concept; the grounder had no matching check.
- Of the first ten counter-edges the adversarial grounder wrote, the grounders rejected four that rested on a
  premise the attacker supplied, on a figure the source gives as support, on a counter the source sets against
  another claim, or on a link between two documents. The lesson lived only in the user's memory notes.
- The orchestrator pasted rules recalled from those notes into a grounder's prompt, among them "the pack has no
  `enables` relation", minutes after 0.8.0 added it. The command text never named `enables`, so nothing on the
  orchestrator's side contradicted the note.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GROUNDER = (REPO / "agents" / "grounder.md").read_text(encoding="utf-8")
EXTRACTOR = (REPO / "agents" / "extractor.md").read_text(encoding="utf-8")
ADVERSARIAL = (REPO / "agents" / "adversarial-grounder.md").read_text(encoding="utf-8")
CMD = (REPO / "commands" / "kg-ground.md").read_text(encoding="utf-8")


def _flat(text: str) -> str:
    return " ".join(text.split())


def _between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def _grounder_template() -> str:
    return _between(CMD, 'subagent_type: "kg-grounder"', '"""\n)')


def _adversarial_template() -> str:
    return _between(CMD, 'subagent_type: "kg-adversarial-grounder"', '"""\n)')


# ---- the grounder ------------------------------------------------------------------------------------

def test_the_grounder_checks_what_each_node_names():
    flat = _flat(GROUNDER)
    assert "**Each end is the concept its span names.**" in flat
    assert "between THESE nodes" in flat                                   # procedure step 1b
    assert '`"wrong-node: <the concept the span names instead>"`' in flat
    note_line = next(line for line in GROUNDER.splitlines() if line.strip().startswith("note      ="))
    assert "wrong-node" in note_line
    assert "vague / no-support / wrong-relation / wrong-node" in flat      # the report's breakdown


def test_the_rule_spares_evidence_about_one_case():
    # a grounds edge's HEAD is often one company's figures for a general claim; the rule is about what a node
    # names, and must not read as "evidence has to be as general as the claim"
    assert ("one company's figures still ground a general claim when the span offers them as evidence for it"
            in _flat(GROUNDER))


def test_the_grounder_names_the_edge_a_rejected_span_does_state():
    report = _flat(_between(GROUNDER, "4. **Report.**", "## Invariants you enforce"))
    assert "For each `wrong-relation` or `wrong-node` rejection, name the edge its span does state" in report


def test_the_extractor_names_the_check_that_backs_its_rule():
    flat = _flat(EXTRACTOR)
    assert "**Never for a broader, narrower or merely related concept.**" in flat
    assert "rejected as `wrong-node` (0.8.1)" in flat


# ---- the adversarial grounder -----------------------------------------------------------------------

def test_the_counter_must_be_the_sources():
    flat = _flat(ADVERSARIAL)
    assert "**the counter must be the source's (0.8.1).**" in flat
    assert "A contradiction that no single span states is not an edge: list it in your report." in flat
    assert ("If no span sets itself against the hub or one of its claims, emit a falsifying question (Output B)."
            in flat)
    assert "Contradictions you found that no single span states" in flat   # report back


def test_the_contract_items_are_numbered_in_order():
    contract = _between(ADVERSARIAL, "## The contract you must honor", "## Bounded run")
    numbers = [int(n) for n in re.findall(r"^(\d+)\. \*\*", contract, flags=re.M)]
    assert numbers == list(range(1, len(numbers) + 1)) and len(numbers) == 6
    assert "(contract item 2)" in _flat(ADVERSARIAL) and "2. **the counter must be the source's" in contract


# ---- the command -------------------------------------------------------------------------------------

def test_the_command_sends_ids_not_rules():
    flat = _flat(CMD)
    assert "**Never paste evidence or rules into a prompt:** give each grounder its item ids and nothing else." in flat
    assert "a precondition is `enables`, never `grounds`" in flat           # the orchestrator now sees enables
    assert "It gives each grounder its item ids and nothing else" in flat   # invariant


def test_the_grounder_template_names_every_reason_the_contract_defines():
    template = _flat(_grounder_template())
    reasons = set(re.findall(r"[a-z]+(?:-[a-z]+)*", GROUNDER.split("name the failure:", 1)[1].splitlines()[0]))
    assert reasons == {"vague", "no-support", "wrong-relation", "wrong-node"}
    # `no-support` is the template's "span_in_source is false"; every other reason is named in backticks
    assert reasons - {"no-support"} <= set(re.findall(r"`([a-z-]+)`", template))
    assert "span_in_source is false" in template
    assert "(`enables`) filed as `grounds`" in template
    assert "between what the two nodes name" in template


def test_the_adversarial_template_asks_for_the_sources_counter():
    template = _flat(_adversarial_template())
    assert "Write a counter-edge only when its span, in its own context, sets itself against the claim it attacks." in template
    assert "the contradictions no single span states" in template


def test_the_report_lists_the_leads():
    report = _flat(_between(CMD, "## Stage 3", "## §Stage 6"))
    assert "Then list the leads the grounders named for an extractor" in report
    assert "an `enables` edge from the same span" in report
    assert "`/kg-build` skips every section that already has one" in report
