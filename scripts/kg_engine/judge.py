"""The blind judge's deterministic half (0.13.0): `/kg-experiment --judge`.

Option D of the Stage 8 method (docs/fusion/EXPERIMENT.md) reads each idea the way a careful reader would. A
judge sees one prompt and every arm's idea plus two controls, each with passages retrieved from the source for
that idea, and scores how well each idea holds in its evidence and how useful it is. Three pilots fixed the
instrument; this module builds the packets and aggregates the verdicts with the rules they pre-declared.

* **Evidence per idea** is the third pilot's rule. Sentences are split into clauses at , ; : and before a
  coordinating conjunction. Each clause's four best BM25 passages are taken in rounds. Then, for each figure or
  name of the idea that the source holds and the evidence still lacks, the best-ranked passage that contains it
  is added. An idea carries at most 20,000 characters.
* **Two controls per prompt**, written by the command: a *decoy* whose central support is invented, and a
  *positive control* whose facts are real and spread over at least two documents. `check_controls` checks both
  before any judge runs.
* **Order.** The items follow a seed-7 permutation rotated by one position per prompt. The label-to-item
  mapping stays in `private/`, out of the judges' reach.
* **Grounded and useful, never novelty.** Evidence retrieved for an idea's own words cannot show that the idea
  paraphrases the source (EXPERIMENT.md, "novelty and paraphrase"), so a judge's novelty could credit an idea
  only for being phrased far from the source.
* **Validity, every run.** V1: the decoy is the least grounded item. V3: the positive control scores 4 or more.
  Each must hold in as many prompts as the sign test needs, 10 of 12. V2: the arms' mean grounded score exceeds
  the decoys' by at least 1.0. If any fails, every judge verdict reads "not measured".
"""
from __future__ import annotations

import json
import random
import re
import statistics
from collections import Counter
from pathlib import Path

from . import harness
from .sources import SourceSet

ARMS = ("control", "graph", "graph+generate", "graph+generate+dpp", "rag", "lightrag")
CONTROLS = ("decoy", "positive")
CRITERIA = ("grounded", "useful")
SEED = 7
EVIDENCE_CHARS = 20_000
ROUNDS = 4
DEPTH = 20
COMMON_WORDS = 400
MIN_CLAUSE_WORDS = 4
MIN_GAP = 1.0
POSITIVE_FLOOR = 4

_CLAUSE = re.compile(r"[,;:]\s+")
# A clause that chains two facts gets passages for each (the second pilot's misses). The rule was calibrated
# on a Spanish corpus; the English coordinators are the same rule for an English one.
_CONJ = re.compile(r"\s(?:y|o|pero|mientras|porque|aunque|sino|and|or|but|while|because|although)\s")
_FIGURE = re.compile(r"\d+(?:[.,]\d+)*(?:\s?%)?")
_TOKEN = re.compile(r"[^\W\d_][\w-]*")
_SENTENCE_START = re.compile(r"(?:^|[.!?:]\s+)$")


class Evidence:
    """Evidence per idea, from the source's paragraphs (the third pilot's rule)."""

    def __init__(self, documents: dict[str, str]):
        self.documents = documents
        self.text = "\n".join(documents.values())
        lower = [w for w in _TOKEN.findall(self.text) if w == w.lower()]
        self.common = {w for w, _ in Counter(lower).most_common(COMMON_WORDS)}
        self._ranked: dict[str, list[dict]] = {}

    def _holds_name(self, name: str) -> bool:
        return re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", self.text) is not None

    def terms(self, text: str, skip_initial: bool = False) -> tuple[set, set]:
        """(held, invented): the idea's figures of two digits or more and its capitalised names (not one of
        the source's commonest words), split by whether the source holds them. `skip_initial` leaves out a
        word that is capitalised only because it opens a sentence, so the control checks do not read a
        sentence's first word as a name."""
        held, invented = set(), set()
        for m in _FIGURE.finditer(text):
            figure = m.group(0).strip()
            if len(re.sub(r"\D", "", figure)) >= 2:
                (held if figure in self.text else invented).add(figure)
        for m in _TOKEN.finditer(text):
            word = m.group(0)
            if len(word) < 2 or not word[0].isupper() or word.lower() in self.common:
                continue
            if skip_initial and _SENTENCE_START.search(text[:m.start()]) and not word.isupper():
                continue
            (held if self._holds_name(word) else invented).add(word)
        return held, invented

    @staticmethod
    def clauses(text: str) -> list[str]:
        parts = [c for s in harness._SENT.split(text) for c in _CLAUSE.split(s)]
        parts = [c2 for c in parts for c2 in _CONJ.split(c)]
        return [c for c in parts if len(c.split()) >= MIN_CLAUSE_WORDS]

    def prepare(self, texts) -> None:
        """Rank every clause of `texts` in one BM25 pass (the index is built once)."""
        todo = sorted({c for t in texts for c in self.clauses(t)} - set(self._ranked))
        if todo:
            for clause, ranked in zip(todo, harness.rag_slices(todo, self.documents, budget_tokens=100_000)):
                self._ranked[clause] = ranked[:DEPTH]

    def build(self, text: str) -> list[dict]:
        self.prepare([text])
        ranked = [self._ranked[c] for c in self.clauses(text)]
        seen, out, used = set(), [], 0

        def add(passage: dict) -> bool:
            nonlocal used
            key = (passage["document"], passage["text"])
            if key in seen or used + len(passage["text"]) > EVIDENCE_CHARS:
                return False
            seen.add(key)
            out.append(passage)
            used += len(passage["text"])
            return True

        for depth in range(ROUNDS):
            for passages in ranked:
                if len(passages) > depth:
                    add(passages[depth])
        have = " ".join(p["text"] for p in out)
        for term in sorted(self.terms(text)[0]):
            if term in have:
                continue
            for passages in ranked:
                hit = next((p for p in passages if term in p["text"]), None)
                if hit and add(hit):
                    have += " " + hit["text"]
                    break
        return out


def item_order(items: list[str], index: int) -> list[str]:
    """The seed-7 permutation of `items`, rotated by `index` positions: over len(items) prompts every item
    takes every position once."""
    base = list(items)
    random.Random(SEED).shuffle(base)
    r = index % len(base)
    return base[r:] + base[:r]


def check_controls(evidence: Evidence, decoys: list[str], positives: list[str]) -> list[dict]:
    """Each prompt's two controls, checked before any judge runs:
    - the decoy cites at least one study, organisation or figure the source does not hold;
    - the positive control cites nothing the source lacks, holds two or more figures or names of the source,
      carries every one of them in its own evidence, and draws them from at least two documents."""
    results = []
    for k, (decoy, positive) in enumerate(zip(decoys, positives), 1):
        problems = []
        if not evidence.terms(decoy, skip_initial=True)[1]:
            problems.append("the decoy cites no name or figure the source lacks; its central support must be invented")
        held, invented = evidence.terms(positive, skip_initial=True)
        if invented:
            problems.append(f"the positive control cites what the source does not hold: {sorted(invented)}")
        if len(held) < 2:
            problems.append("the positive control cites fewer than two figures or names that the source holds")
        passages = evidence.build(positive)
        missing = sorted(t for t in held if not any(t in p["text"] for p in passages))
        if missing:
            problems.append(f"the positive control's evidence lacks {missing}")
        if len({p["document"] for p in passages if any(t in p["text"] for t in held)}) < 2:
            problems.append("the positive control's facts come from fewer than two documents")
        results.append({"prompt": k, "ok": not problems, "problems": problems})
    return results


def _render(k: int, n: int, prompt: str, order: list[str], texts: dict, evidence: Evidence, sizes: list) -> str:
    lines = [f"# Packet {k + 1} of {n}", "", "## Prompt", "", prompt, ""]
    for label, item in zip(_labels(len(order)), order):
        lines += [f"## Idea {label}", "", texts[(item, k)], "", f"### Evidence for idea {label}", ""]
        passages = evidence.build(texts[(item, k)])
        sizes.append(sum(len(p["text"]) for p in passages))
        for j, p in enumerate(passages, 1):
            lines += [f"Passage {j} ({p['document']}):", ""] + ["> " + ln for ln in p["text"].splitlines()] + [""]
    return "\n".join(lines)


def _labels(count: int) -> list[str]:
    if count > 26:
        raise ValueError(f"{count} items do not fit labels A-Z")
    return [chr(ord("A") + i) for i in range(count)]


def build_packets(outputs: dict, prompts: list[str], documents: dict, decoys: list[str], positives: list[str],
                  out_dir) -> dict:
    """Write one packet per prompt to `out_dir/packets/NN.md` and the label mapping to
    `out_dir/private/mapping.json`, once both controls of every prompt pass `check_controls`. Returns a
    summary; `written` is False, and nothing but `private/checks.json` is written, when a control fails."""
    n = len(prompts)
    arms = [a for a in ARMS if a in outputs]
    if n == 0 or not arms:
        raise ValueError("the judge needs prompts and at least one arm's ideas")
    for arm in arms:
        if not (isinstance(outputs[arm], list) and len(outputs[arm]) == n and all(isinstance(x, str) for x in outputs[arm])):
            raise ValueError(f"outputs[{arm!r}] must hold one idea per prompt ({n})")
    if len(decoys) != n or len(positives) != n:
        raise ValueError(f"the controls file must hold {n} decoys and {n} positives, one per prompt")
    out = Path(out_dir)
    if (out / "verdicts").is_dir() and any((out / "verdicts").glob("*.json")):
        raise ValueError(f"{out / 'verdicts'} already holds verdicts; judge a run in a fresh folder")
    evidence = Evidence(documents)
    items = arms + list(CONTROLS)
    texts = {(item, k): (decoys[k] if item == "decoy" else positives[k] if item == "positive" else outputs[item][k])
             for item in items for k in range(n)}
    evidence.prepare(texts.values())
    checks = check_controls(evidence, decoys, positives)
    (out / "private").mkdir(parents=True, exist_ok=True)
    _write_json(out / "private" / "checks.json", checks)
    if not all(c["ok"] for c in checks):
        return {"written": False, "checks": [c for c in checks if not c["ok"]]}
    (out / "packets").mkdir(exist_ok=True)
    width = max(2, len(str(n)))
    mapping, sizes, total = {"items": items, "seed": SEED, "packets": {}}, [], 0
    for k, prompt in enumerate(prompts):
        order = item_order(items, k)
        text = _render(k, n, prompt, order, texts, evidence, sizes)
        path = out / "packets" / f"{k + 1:0{width}d}.md"
        path.write_text(text, encoding="utf-8", newline="\n")
        total += len(text.encode("utf-8"))
        mapping["packets"][f"{k + 1:0{width}d}"] = dict(zip(_labels(len(order)), order))
    _write_json(out / "private" / "mapping.json", mapping)
    return {"written": True, "packets": n, "items": items, "bytes": total,
            "evidence_chars": {"min": min(sizes), "max": max(sizes), "mean": round(statistics.mean(sizes))}}


def _verdict_problem(verdict, labels: dict) -> "str | None":
    if not isinstance(verdict, dict):
        return "not a JSON object"
    scores, ranking = verdict.get("scores"), verdict.get("ranking")
    if not isinstance(scores, dict) or not isinstance(ranking, list):
        return "needs 'scores' and 'ranking'"
    if sorted(map(str, ranking)) != sorted(labels) or len(set(ranking)) != len(ranking):
        return f"ranking {ranking} is not a strict order of {sorted(labels)}"
    for label in labels:
        s = scores.get(label)
        if not isinstance(s, dict):
            return f"no scores for {label}"
        for c in CRITERIA:
            v = s.get(c)
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5:
                return f"{label}.{c} must be an integer from 1 to 5"
    return None


def aggregate(judge_dir, outputs: "dict | None" = None) -> dict:
    """The judges' verdicts under the pre-declared rules: V1-V3, then each pair of `harness._PAIRS` whose arms
    were judged, decided on the judges' rankings by the one-sided sign test. A missing or malformed verdict
    drops its prompt and is listed under `problems`."""
    d = Path(judge_dir)
    mapping = json.loads((d / "private" / "mapping.json").read_text(encoding="utf-8"))
    items = mapping["items"]
    arms = [i for i in items if i not in CONTROLS]
    per, problems = {}, []
    for key, labels in sorted(mapping["packets"].items()):
        try:
            verdict = json.loads((d / "verdicts" / f"{key}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            problems.append(f"{key}: no readable verdict ({e.__class__.__name__})")
            continue
        problem = _verdict_problem(verdict, labels)
        if problem:
            problems.append(f"{key}: {problem}")
        else:
            per[key] = verdict
    n = len(per)
    needed = harness.sign_test_needed(n) if n else None
    by = {k: {item: label for label, item in mapping["packets"][k].items()} for k in per}

    def score(k, item, c):
        return per[k]["scores"][by[k][item]][c]

    v1 = sum(score(k, "decoy", "grounded") <= min(score(k, i, "grounded") for i in items if i != "decoy") for k in per)
    v3 = sum(score(k, "positive", "grounded") >= POSITIVE_FLOOR for k in per)
    gap = (round(statistics.mean(score(k, a, "grounded") for k in per for a in arms)
                 - statistics.mean(score(k, "decoy", "grounded") for k in per), 3) if per else None)
    checks = {
        "v1_decoy_least_grounded": {"prompts": v1, "of": n, "needed": needed,
                                    "passed": needed is not None and v1 >= needed},
        "v2_grounded_gap": {"gap": gap, "needed": MIN_GAP, "passed": gap is not None and gap >= MIN_GAP},
        "v3_positive_grounded": {"prompts": v3, "of": n, "needed": needed,
                                 "passed": needed is not None and v3 >= needed},
    }
    if needed is None:
        reason = f"too few prompts judged ({n}; the sign test needs at least 5)"
    else:
        failed = [name for name, c in checks.items() if not c["passed"]]
        reason = ("the judge failed its validity checks (" + ", ".join(failed) + ")") if failed else None
    valid = reason is None
    order = {k: [mapping["packets"][k][label] for label in per[k]["ranking"]] for k in per}
    result = {"n": n, "problems": problems, "checks": checks, "valid": valid, "comparisons": {}}
    for key, x, y, label in harness._PAIRS:
        if x not in arms or y not in arms:
            continue
        wins = sum(order[k].index(x) < order[k].index(y) for k in per)
        result["comparisons"][f"{x} vs {y}"] = {"n": n, "wins": wins, "losses": n - wins, "needed": needed}
        if not valid:
            result[key] = f"not measured: {reason}"
        elif wins >= needed:
            result[key] = f"{x} beat {label} in the judges' ranking in {wins} of {n} prompts"
        else:
            result[key] = f"{x} did NOT clearly beat {label} in the judges' ranking ({wins} of {n} prompts; {needed} needed)"
    if per:
        result["means"] = {i: {c: round(statistics.mean(score(k, i, c) for k in per), 2) for c in CRITERIA} for i in items}
        result["mean_rank"] = {i: round(statistics.mean(order[k].index(i) + 1 for k in per), 2) for i in items}
        result["first_by_label"] = dict(sorted(Counter(per[k]["ranking"][0] for k in per).items()))
    if outputs:
        result["words"] = {a: round(statistics.mean(len(x.split()) for x in outputs[a]), 1)
                           for a in arms if outputs.get(a)}
    return result


def _write_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")


def _load_outputs(path: str) -> dict:
    try:
        blob = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise harness._LoadError(f"could not read the outputs file {path}: {e}") from None
    if not isinstance(blob, dict) or not isinstance(blob.get("outputs"), dict):
        raise ValueError('the outputs file must be a JSON object like {"outputs": {...}}')
    return blob["outputs"]


def cmd_packets(argv: list[str]) -> int:
    """judge-packets OUTPUTS PROMPTS SOURCE CONTROLS OUT_DIR: exit 0 with the packets written, 3 when a
    control failed its check (the failures are printed; no packet is written)."""
    outputs_path, prompts_path, source, controls_path, out_dir = (harness._positional_path(argv, i) for i in range(1, 6))
    if not (outputs_path and prompts_path and source and controls_path and out_dir):
        raise ValueError("usage: judge-packets OUTPUTS PROMPTS SOURCE CONTROLS OUT_DIR")
    from .lightrag_arm import _load_prompts
    try:
        prompts = _load_prompts(Path(prompts_path))
        controls = json.loads(Path(controls_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise harness._LoadError(f"could not read the prompts or the controls: {e}") from None
    if not isinstance(controls, dict):
        raise ValueError('the controls file must be a JSON object like {"decoys": [...], "positives": [...]}')
    files = SourceSet.resolve(source)
    if not files:
        raise harness._LoadError(f"source path not found or holds no .md/.txt document: {source}")
    if not Path(source).is_file() and any(Path(out_dir).resolve() == p.parent.resolve() for p in files):
        raise harness._LoadError(f"{out_dir} is a folder the source reads its documents from; "
                                 "judge under the project's .kg/.")
    result = build_packets(_load_outputs(outputs_path), prompts, SourceSet(source).texts,
                           list(controls.get("decoys") or []), list(controls.get("positives") or []), out_dir)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["written"] else 3


def cmd_aggregate(argv: list[str]) -> int:
    """judge-aggregate JUDGE_DIR [OUTPUTS]: print the aggregate as JSON."""
    judge_dir = harness._positional_path(argv, 1)
    if not judge_dir:
        raise ValueError("usage: judge-aggregate JUDGE_DIR [OUTPUTS]")
    if not (Path(judge_dir) / "private" / "mapping.json").is_file():
        raise harness._LoadError(f"no packets were built in {judge_dir} (private/mapping.json is missing)")
    outputs_path = harness._positional_path(argv, 2)
    print(json.dumps(aggregate(judge_dir, _load_outputs(outputs_path) if outputs_path else None),
                     ensure_ascii=False, indent=1))
    return 0
