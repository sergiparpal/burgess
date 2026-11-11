"""Validation harness (§Stages 7-8): annotation agreement, the specificity metric, ideation scoring.

Everything here is deterministic measurement over data the subagents produce. No metric gates the
pipeline — each prints a number and a verdict; the orchestration logs it and proceeds (§4).
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from .graphio import node_link_graph
from .sources import SourceSet, section_corpus

# --------------------------------------------------------------------------- Krippendorff's alpha


def agreement(label_sets: list[dict]) -> float:
    """Nominal Krippendorff's alpha across independent coders.

    `label_sets`: one dict per coder, mapping unit_id -> label. Units rated by <2 coders are ignored.
    Returns alpha in (-inf, 1]; 1.0 = perfect agreement, 0 = chance, <0 = systematic disagreement.
    """
    # shape guard: label_sets is a list of per-coder {unit: label} dicts. A top-level JSON object
    # (a single dict) would otherwise iterate its KEYS as "coders" and raise an opaque AttributeError
    # on coder.items() — surface a usage error instead.
    if not isinstance(label_sets, list) or not all(isinstance(c, dict) for c in label_sets):
        raise ValueError("label_sets must be a list of {unit: label} dicts")
    # gather ratings per unit
    per_unit: dict = defaultdict(list)
    for coder in label_sets:
        for unit, label in coder.items():
            # store the SAME stripped form used for the emptiness test, so cosmetic whitespace
            # variants of a label ("correct" vs "correct ") aren't scored as distinct categories.
            s = str(label).strip() if label is not None else ""
            if s != "":
                per_unit[unit].append(s)
    units = {u: vals for u, vals in per_unit.items() if len(vals) >= 2}
    if not units:
        return float("nan")

    # coincidence matrix
    o: dict = defaultdict(float)
    for vals in units.values():
        m = len(vals)
        cnt = Counter(vals)
        for c in cnt:
            for k in cnt:
                pairs = cnt[c] * (cnt[c] - 1) if c == k else cnt[c] * cnt[k]
                o[(c, k)] += pairs / (m - 1)

    cats = sorted({c for (c, _) in o})
    n_c = {c: sum(o[(c, k)] for k in cats) for c in cats}
    n = sum(n_c.values())
    if n <= 1:
        return float("nan")

    # nominal metric: 1 if c != k else 0
    do = sum(o[(c, k)] for c in cats for k in cats if c != k) / n
    de = sum(n_c[c] * n_c[k] for c in cats for k in cats if c != k) / (n * (n - 1))
    if de == 0:
        return 1.0
    return 1.0 - do / de


# --------------------------------------------------------------------------- IDF / specificity

# A word starts with a letter and has at least two characters, so short alpha labels like "AI"/"ML"/"OS"
# still match a term and carry their IDF rarity into node_specificity, instead of matching nothing and
# silently falling back to the corpus default (finding harness-f4-4). Single-char tokens stay excluded as
# noise. Determinism is unaffected — the same regex drives idf_seeds, _ngrams, the support check's key terms,
# node_specificity and the rag arm's retrieval alike.
#
# Letters are Unicode letters (0.11.8). The pattern was `[A-Za-z][A-Za-z0-9_-]{1,}` through 0.11.7, which
# cut every word at its first letter outside ASCII: on the Windows corpus (Spanish, 2026-11-10) "revisión"
# scored as "revisi", "Ámbito" as "mbito" and "más" not at all, in 214 of the graph's 425 node labels and in
# every ideation output. On ASCII text the two patterns find the same words.
_WORD = re.compile(r"[^\W\d_][\w-]+")


def idf_seeds(documents: list[str]) -> dict[str, float]:
    """IDF per term over a corpus of documents (sections). Higher = more specific/rarer."""
    n = max(len(documents), 1)
    df: Counter = Counter()
    for doc in documents:
        for term in set(w.lower() for w in _WORD.findall(doc)):
            df[term] += 1
    return {t: math.log(n / (1 + d)) + 1.0 for t, d in df.items()}


def node_specificity(label: str, seeds: dict[str, float], default: float) -> float:
    terms = [w.lower() for w in _WORD.findall(label or "")]
    if not terms:
        return default
    return sum(seeds.get(t, default) for t in terms) / len(terms)


# rank-churn gate: specificity-weighting only earns promotion when the top-betweenness leaders move by
# more than this fraction once weighted (§1.4/§1.6). Advisory knob — the harness measures, never gates.
_CHURN_GATE = 0.2


def specificity(graph_data: dict, corpus: list[str], *, precomputed_betweenness: dict | None = None,
                precomputed_seeds: dict | None = None, precomputed_undirected=None) -> dict:
    """Compare specificity-weighted betweenness vs raw degree vs raw betweenness.

    Verdict: does specificity-weighting separate real bridges from vague high-traffic nodes beyond a
    churn band? If yes, the gated metric (§1.4/§1.6) earns its place (`gate_on=True`).

    The optional `precomputed_*` inputs let the projector pass the betweenness, RAW idf seeds, and the
    already-built undirected graph it computed in `_ranks` (projector-2/projector-3): without them this
    function re-ran `nx.betweenness_centrality` (a second O(V·E) pass) and `idf_seeds` (a second corpus
    scan) and round-tripped the graph through node-link. The seeds MUST be the raw corpus IDF (NOT the
    pack-merged seeds the projector uses for its own specificity) so the gate verdict is unchanged.
    """
    import networkx as nx

    # shape guard: on the CLI path (precomputed_undirected is None) a top-level JSON array/scalar would
    # reach node_link_graph and raise an opaque AttributeError on `data.get(...)`, escaping _main's
    # ValueError handler. The projector always passes precomputed_undirected, so this only guards the
    # standalone CLI (review-r7).
    if precomputed_undirected is None and not (isinstance(graph_data, dict) and "nodes" in graph_data):
        # Also require the node-link keys, not just dict-ness: a dict WITHOUT `nodes` (e.g. {"foo": 1})
        # passed the old isinstance-only guard and then raised KeyError: 'nodes' in node_link_graph, again
        # escaping _main's (_LoadError, ValueError) handler with a raw traceback (review-fix: harness).
        raise ValueError("graph must be a node-link object (a JSON object with nodes/links)")
    G = precomputed_undirected if precomputed_undirected is not None else node_link_graph(graph_data).to_undirected()
    if G.number_of_nodes() < 3:
        return {"gate_on": False, "reason": "graph too small", "n": G.number_of_nodes()}

    seeds = precomputed_seeds if precomputed_seeds is not None else (idf_seeds(corpus) if corpus else {})
    default = (sum(seeds.values()) / len(seeds)) if seeds else 1.0
    labels = {n: (G.nodes[n].get("label") or n) for n in G.nodes()}
    spec = {n: node_specificity(labels[n], seeds, default) for n in G.nodes()}

    btw = precomputed_betweenness if precomputed_betweenness is not None else nx.betweenness_centrality(G)
    weighted = {n: btw[n] * spec[n] for n in G.nodes()}

    def topk(d, k=5):
        return [n for n, _ in sorted(d.items(), key=lambda x: -x[1])[:k]]

    top_btw, top_w = topk(btw), topk(weighted)
    # generality confound: do raw-betweenness leaders skew toward low specificity?
    mean_spec = sum(spec.values()) / len(spec)
    btw_leader_spec = sum(spec[n] for n in top_btw) / max(len(top_btw), 1)
    confound = btw_leader_spec < mean_spec  # leaders are vaguer than average -> confound present
    churn = len(set(top_btw) ^ set(top_w)) / (2 * max(len(top_btw), 1))  # rank movement
    # if every node has the same specificity (no IDF spread — e.g. a tiny corpus where the default
    # dominates), the weighting can't separate anything and the gate must stay closed regardless of
    # incidental churn. Surface the spread so a degenerate run is legible, not silently "gate ON".
    spread = (max(spec.values()) - min(spec.values())) if spec else 0.0
    has_spread = spread > 1e-9
    gate_on = bool(confound and churn > _CHURN_GATE and has_spread)
    if gate_on:
        verdict = "specificity-weighting earns its place — gate ON"
    elif not has_spread:
        verdict = "specificity is uniform (corpus too small / no IDF spread) — stays advisory"
    else:
        verdict = "specificity-weighting does not clearly separate — stays advisory"
    return {
        "n": G.number_of_nodes(),
        "mean_specificity": round(mean_spec, 3),
        "specificity_spread": round(spread, 3),
        "betweenness_leader_specificity": round(btw_leader_spec, 3),
        "top_raw_betweenness": top_btw,
        "top_specificity_weighted": top_w,
        "rank_churn": round(churn, 3),
        "generality_confound_detected": confound,
        "gate_on": gate_on,
        "verdict": verdict,
    }


# --------------------------------------------------------------------------- convergence gate (§4)

# the high band only EARNS the right to reorder the grounding queue when its grounded-rate beats the
# low band by more than this margin (the §1.6-style "earn promotion before you gate" rule). Advisory
# knob — the harness measures, never gates the pipeline.
_CONVERGENCE_MARGIN = 0.10
# minimum samples PER BAND before the gate may fire — stays closed on a degenerate/small split, exactly
# as the specificity gate stays advisory without IDF spread.
_CONVERGENCE_MIN_BAND = 3


def convergence(history: list[dict]) -> dict:
    """Gate (mirrors §1.6 specificity gating): given a HISTORY of past candidates with their convergence
    count and eventual grounding outcome — ``[{"convergence": int, "grounded": bool}, ...]`` — decide
    whether higher convergence predicts grounding success beyond a margin.

    Split the history into a HIGH band (convergence >= 2 — proposed by multiple distinct mechanisms) and
    a LOW band (convergence == 1 — a single mechanism). If the high band's grounded-rate exceeds the low
    band's by > MARGIN — and NEITHER band is degenerate / too small — convergence has earned the right to
    REORDER the grounding queue (``gate_on=True``); otherwise it STAYS ADVISORY. Like the specificity
    gate, it stays closed on a small or flat sample: until then convergence is displayed but decides
    nothing (G5).
    """
    # shape guard (mirrors agreement()'s): a top-level JSON scalar (e.g. `5`) makes `(history or [])`
    # non-iterable → `for r in 5` raises an opaque TypeError that escapes _main's ValueError handler
    # (raw traceback + exit 1). A list of malformed ROWS is still tolerated below (review-r7).
    if not isinstance(history, list):
        raise ValueError("history must be a list of {convergence, grounded} objects")
    rows = [r for r in (history or []) if isinstance(r, dict)]

    def _conv(r) -> int:
        try:
            return int(r.get("convergence", 1))
        except (TypeError, ValueError):
            return 1

    high = [bool(r.get("grounded")) for r in rows if _conv(r) >= 2]
    low = [bool(r.get("grounded")) for r in rows if _conv(r) <= 1]
    n_high, n_low = len(high), len(low)
    high_rate = (sum(high) / n_high) if n_high else 0.0
    low_rate = (sum(low) / n_low) if n_low else 0.0
    enough = n_high >= _CONVERGENCE_MIN_BAND and n_low >= _CONVERGENCE_MIN_BAND
    gate_on = bool(enough and (high_rate - low_rate) > _CONVERGENCE_MARGIN)
    if gate_on:
        verdict = "convergence earns its place — gate ON"
    elif not enough:
        verdict = "sample too small per band — stays advisory"
    else:
        verdict = "convergence does not clearly predict grounding — stays advisory"
    return {
        "n": len(rows),
        "n_high_band": n_high,
        "n_low_band": n_low,
        "high_band_rate": round(high_rate, 3),
        "low_band_rate": round(low_rate, 3),
        "margin": round(high_rate - low_rate, 3),
        "min_band": _CONVERGENCE_MIN_BAND,
        "gate_on": gate_on,
        "verdict": verdict,
    }


# --------------------------------------------------------------------------- absorption window (§14)


def absorption(graph_data: dict, history: dict, *, now=None, absorb_growth: int = 3) -> dict:
    """Score how long each grounded-from-hypothesized node stays *perturbing* before the graph
    renormalises around it (§14 — novelty has a half-life). PLAN Stage 5.

    `history` maps a tracked node id -> {introduced_at, introduced_degree}; `graph_data` is the CURRENT
    derived graph (node-link). For each tracked node we read two signals:
      - **decay**: how fast its neighbourhood densified after introduction. Fast densification ⇒ the
        graph absorbed it quickly ⇒ low remaining novelty (short half-life).
      - **isolation**: whether it stayed disconnected ⇒ infertile.
    Returns per-node {half_life, status ∈ fertile|absorbed|isolated, ...}. The fertile middle is the
    productive zone: neither trivially absorbed nor isolated.
    """
    G = node_link_graph(graph_data).to_undirected()
    deg = dict(G.degree())
    # `history` comes straight from generations.json, which the server passes UNVALIDATED — a record may
    # be a non-dict or carry a non-numeric field. Guard every read so a malformed file degrades to
    # "skip that record" instead of crashing the kg_absorption tool (review-low).
    def _as_int(x, default=0):
        try:
            return int(x)
        except (TypeError, ValueError):
            return default

    # Coerce a non-dict `history` (e.g. a hand-corrupted generations.json shaped {"tracked": [...]})
    # to {} so the guard below degrades to "no records" instead of crashing on `.items()` — matching
    # this function's documented malformed-input tolerance (review-r8-17).
    history = history if isinstance(history, dict) else {}
    history = {k: v for k, v in history.items() if isinstance(v, dict)}
    if now is None:
        ats = [_as_int(r.get("introduced_at", 0)) for r in history.values()]
        now = (max(ats) + 1) if ats else 1
    out: dict = {}
    for nid, rec in history.items():
        d0 = _as_int(rec.get("introduced_degree", 0))
        d1 = int(deg.get(nid, 0))
        t = max(1, _as_int(now) - _as_int(rec.get("introduced_at", 0)))
        growth = max(0, d1 - d0)
        rate = growth / t
        if d1 <= 0:
            status, half_life = "isolated", None                # stayed disconnected — infertile
        elif growth >= absorb_growth:
            # `growth > 0` guard mirrors the fertile branch: the absorbed branch relies on the implicit
            # absorb_growth>=1 invariant to keep growth>=1, but a caller passing absorb_growth<=0 with a
            # present-but-non-densifying node (growth==0) would divide by zero here (review-low).
            status = "absorbed"
            half_life = round(t / growth, 3) if growth > 0 else None  # densified fast — renormalised now
        else:
            status = "fertile"                                  # the productive middle
            # an unbounded half-life is None, NOT float('inf'): this dict is returned verbatim by the
            # kg_absorption MCP tool and inf serializes to the bareword `Infinity` (invalid per RFC 8259,
            # breaks a strict client JSON.parse). `status` already distinguishes isolated/fertile.
            half_life = round(t / growth, 3) if growth > 0 else None
        out[nid] = {"half_life": half_life, "status": status, "introduced_degree": d0,
                    "current_degree": d1, "densification": growth, "densification_rate": round(rate, 3)}
    return out


# --------------------------------------------------------------------------- ideation scoring

_SENT = re.compile(r"[.!?]+\s+")

# A "key term" is a word longer than this. A sentence is judged for support when it has at least four words
# and at least _MIN_KEY_TERMS key terms; shorter or vaguer sentences are left out of both sides of the mean.
_KEY_TERM_MIN_LEN = 5
_MIN_KEY_TERMS = 2
_STEM_CHARS = 6                          # support compares key terms by their first six folded characters
_UTILITY_SATURATION = 5                  # utility hits saturate the per-output score at this count
# The causal/structural marker terms whose presence counts as "utility" in an ideation output —
# named beside its saturation knob instead of living inline in the scoring loop (review-r5).
_UTILITY_MARKERS = re.compile(r"\bbecause\b|\bif\b|\btherefore\b|\bbridge|\bconnect")

# The 0.12.0 method (docs/fusion/EXPERIMENT.md, "Stage 8 method, 0.12.0"): ideas are scored on grounded
# novelty — novelty × support — and arms are compared prompt by prompt with a sign test. Every constant below
# is the pre-declared one; none was tuned on a field run.
#
# Through 0.11.x the verdict needed graph ≥ control on novelty, which is distance from a source the control arm
# never sees (0.91 against 0.71-0.76 on three field runs), and its unsupported-claim guard called a sentence
# supported when any of its first three long words occurred anywhere in the source (blind on a 445,018-char
# corpus: 140/143, 171/173 and 181/181 probes passed). Support is now weighted: a sentence's support is the share
# of its key terms' IDF weight that the source holds, so a common word that every paragraph has counts for little
# and a term the source lacks, an invented one, counts the most. Terms are compared by stem, so an inflection the
# source does not use is not taken for an invention.
_UNSUPPORTED_BELOW = 0.5        # a judged sentence whose best paragraph covers less than this counts as unsupported
_MIN_SUPPORT_GAP = 0.10         # instrument check: rag's mean support must exceed control's by at least this
_TIE_BAND = 0.005               # a per-prompt difference within this is a tie
_SIGN_ALPHA = 0.05              # one-sided sign-test level for "X beats Y"
_PROBE_WORD = "zqxjvbrelkf"     # absent from any real text, longer than _KEY_TERM_MIN_LEN


def _ngrams(text: str, n=3) -> set:
    words = [w.lower() for w in _WORD.findall(text)]
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def _as_outputs(outputs) -> list[str]:
    """One condition's ideas as a list of strings, whatever the JSON held."""
    # A condition's value must be a LIST of idea strings. A bare string would otherwise iterate
    # CHARACTER-by-character (`for o in outputs`), scoring `n=len(string)` with 0 diversity/novelty
    # — a plausible-looking but meaningless result rather than an error (review-r8-18). Wrap a lone string
    # as one idea; coerce any other non-list (dict / number / None) to no outputs.
    if isinstance(outputs, str):
        outputs = [outputs]
    elif not isinstance(outputs, list):
        outputs = []
    # Coerce the ELEMENTS too, not just the container: a non-string idea (a number/dict/None from
    # malformed JSON) reaches _ngrams(o)/o.lower() and raises TypeError/AttributeError, which is
    # NOT caught by _main's `except (_LoadError, ValueError)` — so the CLI dies with a raw traceback
    # instead of the intended clean usage exit. Drop non-strings (review: harness ideation crashes on
    # non-string outputs/source).
    return [o for o in outputs if isinstance(o, str)]


def _by_prompt(outputs) -> list[str]:
    """One condition's ideas kept in prompt order, a non-string idea read as an empty one, so position k is
    always prompt k (the paired comparison needs that; `_as_outputs` drops instead)."""
    if isinstance(outputs, str):
        outputs = [outputs]
    elif not isinstance(outputs, list):
        outputs = []
    return [o if isinstance(o, str) else "" for o in outputs]


def _stem(word: str) -> str:
    """A key term as support compares it: accents and case folded, cut to its first _STEM_CHARS characters, so
    an inflection the source does not use ("compararía" where it says "compara") still counts as present."""
    return _fold(word)[:_STEM_CHARS]


def _sentence_stems(sentence: str) -> list[str]:
    """A sentence's key terms (words longer than _KEY_TERM_MIN_LEN) as stems, in order of first use, each once."""
    out: list[str] = []
    for w in _WORD.findall(sentence):
        if len(w) > _KEY_TERM_MIN_LEN:
            s = _stem(w)
            if s not in out:
                out.append(s)
    return out


def _judged_sentences(idea: str) -> list[list[str]]:
    """The key-term stems of each sentence of one idea that support can judge, in order."""
    stems = [_sentence_stems(s) for s in _SENT.split(idea) if len(s.split()) >= 4]
    return [t for t in stems if len(t) >= _MIN_KEY_TERMS]


class _SupportIndex:
    """The source's key-term stems and their weights: each stem's BM25-form IDF over the source's paragraphs
    (cut as `rag-slices` cuts them). A stem no paragraph holds has df 0, the highest weight."""

    def __init__(self, documents: "dict[str, str] | None" = None, source_text: str = ""):
        texts = list(documents.values()) if documents else [source_text or ""]
        passages = [p for text in texts for p in _passages(text)]
        self.n = len(passages)
        df: Counter = Counter()
        for p in passages:
            df.update({_stem(w) for w in _WORD.findall(p) if len(w) > _KEY_TERM_MIN_LEN})
        self._df = df

    def idf(self, stem: str) -> float:
        d = self._df.get(stem, 0)
        return math.log((self.n - d + 0.5) / (d + 0.5) + 1.0)

    def coverage(self, stems: list[str]) -> float:
        """The share of `stems`' total IDF weight held by stems the source contains (0 with no source). Summed
        in sorted order so the floating-point result never depends on hash order."""
        ordered = sorted(set(stems))
        total = sum(self.idf(s) for s in ordered)
        if not total or not self.n:
            return 0.0
        return sum(self.idf(s) for s in ordered if s in self._df) / total


def _idea_scores(idea: str, src_ng: set, index: _SupportIndex) -> dict:
    """novelty, support, grounded novelty, the share of unsupported judged sentences (None when none was
    judged) and the probe's coverage drops, for one idea."""
    ong = _ngrams(idea)
    # an empty/too-short output has no n-grams; score it 0 novelty rather than a free 1.0, so a
    # condition can't game the experiment by emitting blank or one-word "ideas".
    novelty = (1.0 - len(ong & src_ng) / len(ong)) if ong else 0.0
    covs, drops = [], []
    for terms in _judged_sentences(idea):
        c = index.coverage(terms)
        covs.append(c)
        drops.append(c - index.coverage([_PROBE_WORD] + terms[1:]))
    support = sum(covs) / len(covs) if covs else 0.0
    return {"novelty": novelty, "support": support, "grounded": novelty * support,
            "unsupported": (sum(1 for c in covs if c < _UNSUPPORTED_BELOW) / len(covs)) if covs else None,
            "drops": drops}


def _score_condition(outputs: list[str], source_text: str, index: "_SupportIndex | None" = None) -> dict:
    outputs = _as_outputs(outputs)
    # coerce a non-string source like the outputs (review: harness ideation crashes on non-string source)
    source_text = source_text if isinstance(source_text, str) else ""
    if not outputs:
        return {"n": 0, "diversity": 0.0, "novelty": 0.0, "support": 0.0, "grounded_novelty": 0.0,
                "utility": 0.0, "unsupported_rate": 0.0}
    index = index if index is not None else _SupportIndex(source_text=source_text)
    all_ng: Counter = Counter()
    for o in outputs:
        all_ng.update(_ngrams(o))
    diversity = (len(all_ng) / max(sum(all_ng.values()), 1))
    src_ng = _ngrams(source_text)
    scores = [_idea_scores(o, src_ng, index) for o in outputs]
    util = [min(1.0, len(_UTILITY_MARKERS.findall(o.lower())) / _UTILITY_SATURATION) for o in outputs]
    unsupported = [s["unsupported"] for s in scores if s["unsupported"] is not None]
    mean = lambda xs: sum(xs) / len(xs)  # noqa: E731 — every list here is non-empty
    return {
        "n": len(outputs),
        "diversity": round(diversity, 3),
        "novelty": round(mean([s["novelty"] for s in scores]), 3),
        "support": round(mean([s["support"] for s in scores]), 3),
        "grounded_novelty": round(mean([s["grounded"] for s in scores]), 3),
        "utility": round(mean(util), 3),
        "unsupported_rate": round(mean(unsupported), 3) if unsupported else 0.0,
    }


# the canonical arm order for a STABLE, readable `table` — but the scorer never requires any of
# these to be present. `lightrag` (a real, published GraphRAG baseline built over the SAME corpus as
# the flat `rag` arm) is OPTIONAL and off by default: when its outputs are absent the arm is simply
# missing from `table`, never an error. Any non-canonical key is still scored and appended in input
# order, so the harness tolerates whatever arms the evaluator actually emitted.
_CANONICAL_ARMS = ("control", "graph", "graph+generate", "graph+generate+dpp", "rag", "lightrag")

# The pre-declared pairs (EXPERIMENT.md): (output key, X, Y, how Y is named in the verdict).
_PAIRS = (
    ("verdict", "graph", "rag", "rag"),
    ("control_verdict", "graph", "control", "control"),
    ("generate_verdict", "graph+generate", "graph", "graph"),
    ("dpp_verdict", "graph+generate+dpp", "graph+generate", "graph+generate"),
    ("lightrag_verdict", "graph", "lightrag", "the LightRAG baseline"),
)


def _ordered_conditions(outputs_by_condition: dict):
    """Yield (cond, outputs) in canonical arm order, then any extra keys in input order."""
    seen = set()
    for cond in _CANONICAL_ARMS:
        if cond in outputs_by_condition:
            seen.add(cond)
            yield cond, outputs_by_condition[cond]
    for cond, outs in outputs_by_condition.items():
        if cond not in seen:
            yield cond, outs


def sign_test_needed(n: int) -> "int | None":
    """The fewest wins out of n prompts that a one-sided sign test at _SIGN_ALPHA accepts: the smallest k with
    P(Bin(n, 1/2) >= k) <= _SIGN_ALPHA. None when even n of n is not enough (n < 5 at 5 %)."""
    for k in range(n + 1):
        if sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n <= _SIGN_ALPHA:
            return k
    return None


def _paired(xs: list, ys: list) -> dict:
    """X vs Y on per-prompt grounded novelty: wins, losses and ties (within _TIE_BAND) over the prompts both
    have, the wins needed, and the median difference."""
    n = min(len(xs), len(ys))
    diffs = [xs[k] - ys[k] for k in range(n)]
    wins = sum(1 for d in diffs if d > _TIE_BAND)
    losses = sum(1 for d in diffs if d < -_TIE_BAND)
    ordered = sorted(diffs)
    median = (ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2) if n else 0.0
    return {"n": n, "wins": wins, "losses": losses, "ties": n - wins - losses,
            "needed": sign_test_needed(n), "median_diff": round(median, 3)}


def _pair_verdict(x: str, y_name: str, cmp: dict, not_measured: "str | None") -> str:
    if not cmp["n"]:
        return "insufficient data"
    if not_measured:
        return f"not measured: {not_measured}"
    if cmp["needed"] is None:
        return (f"{x} vs {y_name}: too few prompts to decide ({cmp['n']}; a one-sided sign test at 5 % needs at "
                f"least 5)")
    if cmp["wins"] >= cmp["needed"]:
        return f"{x} beat {y_name} on grounded novelty in {cmp['wins']} of {cmp['n']} prompts"
    return (f"{x} did NOT clearly beat {y_name} on grounded novelty ({cmp['wins']} of {cmp['n']} prompts; "
            f"{cmp['needed']} needed)")


def _caveats(table: dict, check: dict) -> list[str]:
    """Plain sentences naming each column or check that cannot tell the arms apart in this run, for the log."""
    out = []
    if check["valid"] is False:
        out.append(
            f"support does not separate text written from the source from text written without it on this "
            f"source: rag's mean support is {check['rag']:.3f} and control's {check['control']:.3f}, a gap of "
            f"{check['gap']:.3f} below the {_MIN_SUPPORT_GAP:.2f} the method requires. Every verdict that uses "
            f"grounded novelty reads not measured.")
    elif check["valid"] is None:
        out.append("support was not checked: the check needs both a rag and a control arm, and this run lacks "
                   "one. The verdicts stand on an unchecked measure.")
    scored = [row for row in table.values() if row.get("n")]
    if scored and all(row.get("utility", 0.0) == 0.0 for row in scored):
        out.append(
            "utility counts only the English markers because, if, therefore, bridge and connect; no arm's "
            "ideas contain one, so the column is 0 everywhere and says nothing about this run. It is not "
            "part of any verdict.")
    return out


def ideation(outputs_by_condition: dict, source_text: str = "",
             documents: "dict[str, str] | None" = None) -> dict:
    """Score each arm and compare the pre-declared pairs prompt by prompt (docs/fusion/EXPERIMENT.md,
    "Stage 8 method, 0.12.0").

    Arm-tolerant: every condition key present is scored (canonical arms first, then any extras), and a pair
    with a missing arm is simply absent from the output. `documents` ({name: text}) gives the source's
    documents one by one, so no paragraph straddles two of them; without it the paragraphs come from
    `source_text`.

    Returns `table` (per arm: n, diversity, novelty, support, grounded_novelty, utility, unsupported_rate),
    `comparisons` (per present pair: wins, losses, ties, n, needed, median_diff), the verdicts of the present
    pairs (`verdict` graph vs rag, `control_verdict`, `generate_verdict`, `dpp_verdict`, `lightrag_verdict`),
    `support_check` and `caveats`. `verdict` is always present ("insufficient data" without both arms)."""
    # shape guard (mirrors agreement()'s): a top-level JSON list — or any non-object — would otherwise
    # reach _ordered_conditions' .items() and raise an opaque AttributeError. Surface a usage error so
    # _main's ValueError handler prints a clean message instead.
    if not isinstance(outputs_by_condition, dict):
        raise ValueError("outputs must be a {condition: [outputs]} object")
    source_text = source_text if isinstance(source_text, str) else ""
    if documents:
        source_text = source_text or "\n".join(documents.values())
    index = _SupportIndex(documents=documents, source_text=source_text)
    src_ng = _ngrams(source_text)
    conds = list(_ordered_conditions(outputs_by_condition))
    table = {cond: _score_condition(outs, source_text, index) for cond, outs in conds}
    per_prompt, drops = {}, []
    for cond, outs in conds:
        scores = [_idea_scores(o, src_ng, index) for o in _by_prompt(outs)]
        per_prompt[cond] = [s["grounded"] for s in scores]
        for s in scores:
            drops.extend(s["drops"])

    rag, control = table.get("rag"), table.get("control")
    check = {"rag": None, "control": None, "gap": None, "min_gap": _MIN_SUPPORT_GAP, "valid": None,
             "probe_drop": round(sum(drops) / len(drops), 3) if drops else None, "probes": len(drops)}
    if rag and control and rag["n"] and control["n"]:
        gap = rag["support"] - control["support"]
        check.update(rag=rag["support"], control=control["support"], gap=round(gap, 3),
                     valid=gap >= _MIN_SUPPORT_GAP)
    not_measured = ("support does not separate rag from control on this source" if check["valid"] is False
                    else None)

    out: dict = {"table": table, "comparisons": {}, "verdict": "insufficient data"}
    for key, x, y, y_name in _PAIRS:
        if x not in per_prompt or y not in per_prompt:
            continue
        cmp = _paired(per_prompt[x], per_prompt[y])
        out["comparisons"][f"{x} vs {y}"] = cmp
        out[key] = _pair_verdict(x, y_name, cmp, not_measured)
    out["support_check"] = check
    out["caveats"] = _caveats(table, check)
    return out


# --------------------------------------------------------------------------- the rag arm's context (0.11.8)

# /kg-experiment's rag arm is the prompt plus "a naive flat slice of the source documents: the top text chunks
# by keyword overlap with the prompt". Through 0.11.7 the kg-evaluator subagent built that slice itself. On
# the Windows corpus (2026-11-10) it wrote a retrieval script and ran it through Bash: the run waited 26
# minutes on that one approval, the script crashed twice on the console's cp1252 encoding, and the slice was
# whatever that script did, so no later run could reproduce it. The harness builds it now, the same way on
# every run and with no shell in the subagent: BM25, the standard flat-retrieval baseline, over the source's
# paragraphs, with accents folded so "revision" in a prompt finds "revisión" in the source. No stopword list
# (IDF discounts words every passage has) and no stemming, so it works in any language and stays naive.

_RAG_BUDGET_TOKENS = 2000   # the budget the graph arm's kg_context call gets
_RAG_CHARS_PER_TOKEN = 4    # the estimate that budget is filled with (projector._CHARS_PER_TOKEN)
_RAG_PASSAGE_CHARS = 1200   # longest passage; a longer paragraph is cut at line, then word boundaries
_BM25_K1, _BM25_B = 1.2, 0.75


def _fold(word: str) -> str:
    """A word as retrieval compares it: accents dropped, case folded."""
    decomposed = unicodedata.normalize("NFKD", word)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def _rag_terms(text: str) -> list[str]:
    return [_fold(w) for w in _WORD.findall(text)]


def _cut(block: str, cap: int) -> list[str]:
    """`block` in pieces of at most `cap` characters, cut between lines, and inside a line only between words."""
    if len(block) <= cap:
        return [block]
    pieces, cur = [], ""
    for line in block.splitlines():
        while len(line) > cap:
            at = line.rfind(" ", 0, cap)
            at = at if at > 0 else cap
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(line[:at].rstrip())
            line = line[at:].lstrip()
        if cur and len(cur) + 1 + len(line) > cap:
            pieces.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        pieces.append(cur)
    return [p for p in pieces if p.strip()]


def _passages(text: str) -> list[str]:
    """A document's paragraphs, each heading kept with the paragraph after it, none longer than
    _RAG_PASSAGE_CHARS. A heading alone would score high on its few words and carry nothing to answer from."""
    out, heading = [], ""
    for block in re.split(r"\n[ \t]*\n", text):
        block = block.strip()
        if not block:
            continue
        if all(line.lstrip().startswith("#") for line in block.splitlines()):
            heading = f"{heading}\n{block}" if heading else block
            continue
        if heading:
            block, heading = f"{heading}\n{block}", ""
        out.extend(_cut(block, _RAG_PASSAGE_CHARS))
    if heading:
        out.extend(_cut(heading, _RAG_PASSAGE_CHARS))
    return out


def rag_slices(prompts: list[str], documents: dict[str, str],
               budget_tokens: int = _RAG_BUDGET_TOKENS) -> list[list[dict]]:
    """For each prompt, the source passages flat retrieval returns: BM25 over every document's paragraphs,
    best first, while they fit in `budget_tokens` (the best one always). Each passage is
    `{"document", "score", "text"}`. Deterministic: ties go to the earlier passage in source order, and the
    query's terms are summed in sorted order so the floating-point sum never depends on hash order."""
    passages = [(name, p) for name, text in documents.items() for p in _passages(text)]
    if not passages:
        return [[] for _ in prompts]
    tfs = [Counter(_rag_terms(p)) for _, p in passages]
    lens = [sum(tf.values()) for tf in tfs]
    avg = (sum(lens) / len(lens)) or 1.0
    df: Counter = Counter()
    for tf in tfs:
        df.update(tf.keys())
    n = len(passages)
    idf = {t: math.log((n - d + 0.5) / (d + 0.5) + 1.0) for t, d in df.items()}
    budget = max(0, int(budget_tokens)) * _RAG_CHARS_PER_TOKEN
    out = []
    for prompt in prompts:
        query = sorted(set(_rag_terms(prompt)) & idf.keys())
        ranked = []
        for i, tf in enumerate(tfs):
            norm = _BM25_K1 * (1 - _BM25_B + _BM25_B * lens[i] / avg)
            s = sum(idf[t] * tf[t] * (_BM25_K1 + 1) / (tf[t] + norm) for t in query if t in tf)
            if s > 0:
                ranked.append((-s, i))
        ranked.sort()
        chosen, used = [], 0
        for neg, i in ranked:
            name, text = passages[i]
            if chosen and used + len(text) > budget:
                break
            chosen.append({"document": name, "score": round(-neg, 3), "text": text})
            used += len(text)
        out.append(chosen)
    return out


def _render_rag_context(k: int, total: int, prompt: str, passages: list[dict]) -> str:
    """One prompt's rag context as the evaluator reads it. Scores stay out of it: the D1 run
    (docs/fusion/EXPERIMENT.md) found numbers in a generator's context leaking into its ideas."""
    lines = [f"# Prompt {k} of {total}", "", prompt, ""]
    if not passages:
        lines += ["No passage of the source shares a word with this prompt.", ""]
    for j, p in enumerate(passages, 1):
        lines += [f"## Passage {j} — {p['document']}", "", p["text"], ""]
    return "\n".join(lines)


def write_rag_contexts(prompts: list[str], source: str, out_dir: str,
                       budget_tokens: int = _RAG_BUDGET_TOKENS) -> dict:
    """Write one Markdown file per prompt (`01.md`, `02.md`, …) and an `index.json` of what each holds
    (documents and scores, no text) into `out_dir`; return the index. `out_dir` may not be a folder the
    source reads its documents from, where the files would become source documents themselves."""
    files = SourceSet.resolve(source)
    if not files:
        raise _LoadError(f"source path not found or holds no .md/.txt document: {source}")
    target = Path(out_dir)
    # a one-file source reads that file only, so its folder may hold anything; a folder or a glob reads
    # the documents beside each other
    if not Path(source).is_file() and any(target.resolve() == p.parent.resolve() for p in files):
        raise _LoadError(f"{out_dir} is a folder the source reads its documents from; "
                         "the contexts would become source documents. Write them under the project's .kg/.")
    if not prompts:
        raise ValueError("the prompts file holds no prompt")
    slices = rag_slices(prompts, SourceSet(source).texts, budget_tokens)
    target.mkdir(parents=True, exist_ok=True)
    width = max(2, len(str(len(prompts))))
    index = {"source": str(source), "budget_tokens": int(budget_tokens), "prompts": []}
    for k, (prompt, passages) in enumerate(zip(prompts, slices), 1):
        name = f"{k:0{width}d}.md"
        with open(target / name, "w", encoding="utf-8", newline="\n") as f:
            f.write(_render_rag_context(k, len(prompts), prompt, passages))
        index["prompts"].append({"file": name, "prompt": prompt,
                                 "passages": [{"document": p["document"], "score": p["score"],
                                               "chars": len(p["text"])} for p in passages]})
    with open(target / "index.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
        f.write("\n")
    return index


# --------------------------------------------------------------------------- who wrote a labeled edge (0.11.7)

# The canon keeps every edge it has accepted since the first build, and an edge does not record which plugin
# version wrote it. A /kg-eval sample is therefore not "the extractor's output": on the Windows corpus
# (2026-11-10) it held first-build extractions from before 0.8.0, edges a `/kg-build --leads` pass wrote
# and counter-edges from adversarial passes, and the run recommended extractor rules the extractor had
# carried since 0.8.0-0.11.0. What the canon does record is each edge's writer mark and its verdict.

def _value(x) -> str:
    return str(getattr(x, "value", x))


def edge_writer(edge) -> str:
    """Which part of Burgess wrote a canon edge, from what the canon records about it.

    `counter-edge`: its notes open with the mark an adversarial pass of /kg-ground leaves.
    `lead`: its notes open with ``lead (from <edge-id>)``, written by `/kg-build --leads`.
    `proposal`: still in the hypothesized lane, written by /kg-generate.
    Otherwise its `authored_by`, with `agent` read as `extractor` (a /kg-build extraction)."""
    from .groundplan import attacked_hub, lead_from  # lazy: `import kg_engine.harness` stays light
    if attacked_hub(edge.notes):
        return "counter-edge"
    if lead_from(edge.notes):
        return "lead"
    if _value(edge.provenance) == "hypothesized":
        return "proposal"
    by = _value(edge.authored_by)
    return "extractor" if by == "agent" else by


def sample_writers(rows: list[dict], edges: dict) -> dict:
    """Split a labeled f4_probe sheet by who wrote each edge and by the grounding verdict it holds now.

    `rows` are the sheet's rows (an unlabeled row is skipped, as `f4_probe score` skips it); `edges` maps
    edge id to its canon `Edge`. Returns per-writer and per-verdict counts, the rows labeled other than
    `correct` with their writer and verdict, and the ids the canon no longer holds."""
    by_writer: dict = defaultdict(lambda: [0, 0])
    by_state: dict = defaultdict(lambda: [0, 0])
    other, absent = [], []
    for r in rows:
        verdict = (r.get("verdict") or "").strip().lower()
        if not verdict:
            continue
        eid = (r.get("edge_id") or "").strip()
        edge = edges.get(eid)
        if edge is None:
            absent.append(eid)
            continue
        writer, state, ok = edge_writer(edge), _value(edge.epistemic_state), verdict == "correct"
        for tally, key in ((by_writer, writer), (by_state, state)):
            tally[key][0] += 1
            tally[key][1] += ok
        if not ok:
            other.append({"edge_id": eid, "verdict": verdict, "state": state, "writer": writer})

    def table(tally: dict) -> dict:
        order = sorted(tally.items(), key=lambda kv: (-kv[1][0], kv[0]))
        return {k: {"labeled": n, "correct": c} for k, (n, c) in order}

    other.sort(key=lambda o: (o["writer"], o["state"], o["verdict"], o["edge_id"]))
    return {"by_writer": table(by_writer), "by_state": table(by_state), "not_correct": other,
            "absent": absent}


_WRITER_LEGEND = ("writer: extractor = a /kg-build extraction; lead = written by /kg-build --leads from a "
                  "grounder's lead; counter-edge = an adversarial pass of /kg-ground; proposal = /kg-generate")


def _print_writers(res: dict) -> None:
    print("labeled edges by writer (from each edge's canon notes):")
    print(f"  {'writer':14} {'labeled':>7} {'correct':>8} {'precision':>10}")
    for k, v in res["by_writer"].items():
        print(f"  {k:14} {v['labeled']:7d} {v['correct']:8d} {v['correct'] / v['labeled']:10.2f}")
    print("\nlabeled edges by the grounding verdict they hold now:")
    print(f"  {'verdict':14} {'labeled':>7} {'correct':>8}")
    for k, v in res["by_state"].items():
        print(f"  {k:14} {v['labeled']:7d} {v['correct']:8d}")
    print(f"\nlabeled other than correct ({len(res['not_correct'])}):")
    for o in res["not_correct"]:
        print(f"  {o['verdict']:12} {o['state']:11} {o['writer']:13} {o['edge_id']}")
    if res["absent"]:
        print(f"\nnot in the canon now ({len(res['absent'])}): " + ", ".join(res["absent"]))
    print("\n" + _WRITER_LEGEND)


# --------------------------------------------------------------------------- the log outside the source

# /kg-eval and /kg-experiment append their results to this file under the project's `.kg/` (0.11.7).
LOG_NAME = "PROGRESS.md"


def legacy_log(project, source) -> "Path | None":
    """The `PROGRESS.md` at the top of the project when it is one of the source's documents, else None.

    Through 0.11.6, /kg-eval and /kg-experiment appended their results to `<project>/PROGRESS.md`. The source
    can be the project folder itself, as on the Windows corpus, and `SourceSet` reads every `.md`/`.txt` file
    at the top of a source folder, so the log became one more document: a build would extract it, and
    /kg-experiment's rag arm and its scoring would read it as source. The log now lives in `<project>/.kg/`,
    which `SourceSet` never reads (it skips dot entries). This finds a log an earlier version left in the
    source, so the commands can tell the user. Burgess never moves or deletes it."""
    old = Path(project) / LOG_NAME
    if not source or not old.is_file():
        return None
    for doc in SourceSet.resolve(source):
        try:
            if os.path.samefile(doc, old):
                return old
        except OSError:
            continue
    return None


# --------------------------------------------------------------------------- CLI

# Krippendorff α at or above this is reported RELIABLE; below it the grounding signal stays advisory.
_ALPHA_RELIABLE = 0.67


def _demo_corpus() -> list[str]:
    return ["entropy grounds the arrow of time", "betweenness measures bridges",
            "specificity weights betweenness by term rarity", "the generality confound inflates vague nodes"]


class _LoadError(Exception):
    """A supplied input file exists but could not be read/parsed. Distinct from the absent-file
    case so the CLI never silently scores demo data while the user believes their file was measured."""


def _load_json_or_demo(path, demo, *, notice: str):
    """Load JSON from `path` if it exists, else return `demo` and print the standard fallback `notice`.

    Returns (parsed_or_demo, used_demo). `path` may be None (no arg supplied). A present-but-unparseable
    file raises `_LoadError` rather than falling back to `demo` — silently reporting metrics over demo
    data on a real-but-broken input would be a misleading number, worse than a clean error."""
    if path and Path(path).exists():
        try:
            return json.loads(Path(path).read_text(encoding="utf-8")), False
        except (json.JSONDecodeError, OSError) as e:
            raise _LoadError(f"failed to parse {path}: {e}") from e
    print(f"[harness] {notice}", file=sys.stderr)
    return demo, True


def _main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m kg_engine.harness "
              "{agreement|specificity|ideation|convergence|writers|legacy-log|rag-slices} [path...]\n"
              "  specificity GRAPH [SOURCE]   ideation OUTPUTS [SOURCE]\n"
              "  writers LABELS.csv PROJECT   legacy-log PROJECT SOURCE\n"
              "  rag-slices PROMPTS SOURCE OUT_DIR [BUDGET_TOKENS]\n"
              "  SOURCE is a file, or a folder of .md/.txt documents, read as the projector reads it",
              file=sys.stderr)
        return 2
    cmd = argv[0]
    try:
        return _dispatch(cmd, argv)
    except (_LoadError, ValueError) as e:
        print(f"[harness] {e}", file=sys.stderr)
        return 2


def _positional_path(argv: list[str], index: int = 1, default=None):
    """The optional positional file path most harness commands take (review-r5: the pluck was
    repeated per command)."""
    return argv[index] if len(argv) > index else default


def _source_text(spath: str) -> str:
    """The text of a GIVEN source path, read the way the projector reads the engine's configured source:
    ``SourceSet(path).concat``. A path may be one file, or a folder (or glob) whose ``.md``/``.txt`` files
    are the documents, like the ``source_path`` option. For a single file ``concat`` is byte-identical to
    the file's text, so a one-file corpus reads exactly as before.

    Through 0.11.3 the CLI called ``read_text`` on the path, so a folder source (the Windows corpus is
    eight documents in one folder) died with a raw IsADirectoryError and /kg-eval's specificity step could
    not run. A given path that resolves to no document is an error, never the demo corpus: a verdict over
    demo data would read as a real measurement."""
    if not SourceSet.resolve(spath):
        raise _LoadError(f"source path not found or holds no .md/.txt document: {spath}")
    return SourceSet(spath).concat


def _cmd_agreement(argv: list[str]) -> int:
    demo = [{"e1": "correct", "e2": "vague", "e3": "correct"},
            {"e1": "correct", "e2": "vague", "e3": "fabricated"}]
    label_sets, _ = _load_json_or_demo(_positional_path(argv), demo,
                                       notice="no labels file; using demo label sets")
    a = agreement(label_sets)
    print(f"krippendorff_alpha: {a:.3f}")
    reliable = f"RELIABLE (>={_ALPHA_RELIABLE})" if a >= _ALPHA_RELIABLE else "BELOW THRESHOLD — grounding signal stays advisory"
    print(f"verdict: {reliable}")
    return 0


def _cmd_specificity(argv: list[str]) -> int:
    gpath = _positional_path(argv, 1, "derived/graph.json")
    spath = _positional_path(argv, 2)
    demo = {"directed": True, "nodes": [{"id": "a", "label": "system"}, {"id": "b", "label": "entropy"},
            {"id": "c", "label": "time"}, {"id": "d", "label": "thermodynamic arrow"}],
            "links": [{"source": "a", "target": "b"}, {"source": "a", "target": "c"},
                      {"source": "b", "target": "d"}, {"source": "c", "target": "d"}]}
    gdata, _ = _load_json_or_demo(gpath, demo, notice="no graph.json; using demo graph")
    # Split the source into per-section IDF documents, mirroring projector._corpus(). Feeding the
    # whole file as ONE document makes n=1, every term's document-frequency d=1, so every term
    # gets an identical IDF — specificity collapses to a single value, spread≈0, and the gate
    # verdict is ALWAYS the degenerate "corpus too small / no IDF spread", never reflecting the
    # real graph. The production projector path already splits; this standalone CLI must too.
    if spath:
        # a GIVEN-but-missing source path must NOT silently fall back to the demo corpus — that
        # would yield a degenerate gate verdict read as a real measurement (mirrors
        # _load_json_or_demo, which only falls back when NO path was supplied). _source_text raises.
        text = _source_text(spath)
        # the SAME per-section corpus the projector wires (single home: sources.section_corpus,
        # review-r5) over the SAME SourceSet concat it reads — the gate verdict here only means what the
        # projector computes if the two corpora are bit-identical, and that holds for a folder too.
        corpus = section_corpus(text) or [text]
    else:
        print("[harness] no source; using demo IDF corpus", file=sys.stderr)
        corpus = _demo_corpus()
    res = specificity(gdata, corpus)
    print(json.dumps(res, indent=2))
    return 0


def _cmd_ideation(argv: list[str]) -> int:
    demo = {"source": "entropy grounds the arrow of time",
            "outputs": {"control": ["A is connected to B."],
                        "graph": ["A bridges B and C because entropy grounds time."],
                        "rag": ["A relates to B somehow."]}}
    blob, _ = _load_json_or_demo(_positional_path(argv), demo,
                                 notice="no outputs file; using demo outputs")
    # shape guard BEFORE .get: a top-level JSON array/scalar would otherwise raise an opaque
    # AttributeError here (escaping _main's ValueError handler → raw traceback + exit 1). Surface a
    # clean usage error like ideation()'s own guard does for its argument (review-r7).
    if not isinstance(blob, dict):
        raise ValueError('outputs file must be a JSON object like {"source": ..., "outputs": {...}}')
    src_text = blob.get("source", "")
    # An optional second path names the source itself (0.11.4): /kg-experiment passes the configured
    # source_path here, so the evaluator no longer pastes a whole corpus into the JSON (eight documents on
    # the Windows install). Read like the projector reads it; a given path wins over an embedded "source".
    spath = _positional_path(argv, 2)
    documents = None
    if spath:
        src_text = _source_text(spath)
        documents = SourceSet(spath).texts  # one document at a time, so no paragraph straddles two (0.12.0)
    # when outputs aren't nested under "outputs", treat the rest of the blob as conditions but
    # never let the top-level "source" string leak in as a fake (char-iterated) condition.
    obc = blob.get("outputs", {k: v for k, v in blob.items() if k != "source"})
    res = ideation(obc, src_text, documents=documents)
    print(json.dumps(res, indent=2))
    return 0


def _cmd_convergence(argv: list[str]) -> int:
    # demo: the high band (convergence>=2) grounds at 0.75, the low band (==1) at 0.25 — a clean
    # separation across enough samples, so the gate fires ON (mirrors the specificity/ideation demos).
    demo = [{"convergence": 2, "grounded": True}, {"convergence": 2, "grounded": True},
            {"convergence": 2, "grounded": True}, {"convergence": 2, "grounded": False},
            {"convergence": 1, "grounded": True}, {"convergence": 1, "grounded": False},
            {"convergence": 1, "grounded": False}, {"convergence": 1, "grounded": False}]
    history, _ = _load_json_or_demo(_positional_path(argv), demo,
                                    notice="no history file; using demo convergence history")
    res = convergence(history)
    print(json.dumps(res, indent=2))
    return 0


def _cmd_writers(argv: list[str]) -> int:
    labels, project = _positional_path(argv, 1), _positional_path(argv, 2)
    if not labels or not project:
        raise ValueError("usage: writers LABELS.csv PROJECT  (a filled f4_probe sheet, the project holding canon/)")
    from .canon import CANON_SUBDIR, Canon  # lazy, like edge_writer's groundplan import
    if not Path(labels).is_file():
        raise _LoadError(f"labels sheet not found: {labels}")
    if not (Path(project) / CANON_SUBDIR).is_dir():
        raise _LoadError(f"no {CANON_SUBDIR}/ folder in {project}")
    try:
        with open(labels, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        raise _LoadError(f"could not read {labels}: {e}") from e
    # ensure_layout=False: a read never lays a vault out (canon.Canon.__init__).
    edges = {e.id: e for e in Canon(project, ensure_layout=False).all_edges()}
    _print_writers(sample_writers(rows, edges))
    return 0


def _cmd_legacy_log(argv: list[str]) -> int:
    project, source = _positional_path(argv, 1), _positional_path(argv, 2)
    if not project:
        raise ValueError("usage: legacy-log PROJECT SOURCE")
    old = legacy_log(project, source)
    if old is not None:
        new = Path(project) / ".kg" / LOG_NAME
        print(f"NOTE: {old} is one of the source documents. Through Burgess 0.11.6, /kg-eval and "
              f"/kg-experiment kept their log there; they now write {new}. While it stays in the source "
              f"folder, /kg-build extracts it like any other document and /kg-experiment reads it as source. "
              f"Ask the user to move it out of that folder, for instance into {new.parent}. Burgess never "
              f"moves or deletes it.")
    return 0


def _say(text: str) -> None:
    """Print without dying on a console that cannot spell a character: a Windows pipe defaults to cp1252,
    where the evaluator's own retrieval script crashed twice on 2026-11-10."""
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    print(text.encode(enc, "backslashreplace").decode(enc))


def _cmd_rag_slices(argv: list[str]) -> int:
    prompts_path, source, out_dir = (_positional_path(argv, i) for i in (1, 2, 3))
    if not (prompts_path and source and out_dir):
        raise ValueError("usage: rag-slices PROMPTS SOURCE OUT_DIR [BUDGET_TOKENS]")
    budget = _positional_path(argv, 4)
    try:
        budget = int(budget) if budget is not None else _RAG_BUDGET_TOKENS
    except ValueError:
        raise ValueError(f"BUDGET_TOKENS must be a whole number, not {budget!r}") from None
    if not Path(prompts_path).is_file():
        raise _LoadError(f"prompts file not found: {prompts_path}")
    # the LightRAG arm's own reading rule, so both arms take one prompt file alike (it imports no lightrag)
    from .lightrag_arm import _load_prompts
    try:
        prompts = _load_prompts(Path(prompts_path))
    except (OSError, ValueError) as e:
        raise _LoadError(f"could not read the prompts file {prompts_path}: {e}") from None
    index = write_rag_contexts(prompts, source, out_dir, budget)
    counts = [len(p["passages"]) for p in index["prompts"]]
    docs = {q["document"] for p in index["prompts"] for q in p["passages"]}
    _say(f"wrote {len(counts)} rag contexts to {out_dir}: {min(counts)}-{max(counts)} passages each, "
         f"from {len(docs)} of {len(SourceSet.resolve(source))} documents, up to {budget} tokens each")
    return 0


# command table (review-r5: a fifth metric used to mean copying a whole if-branch inside one long
# _dispatch; now it is one _cmd_* function + one row here).
_COMMANDS = {
    "agreement": _cmd_agreement,
    "specificity": _cmd_specificity,
    "ideation": _cmd_ideation,
    "convergence": _cmd_convergence,
    "writers": _cmd_writers,
    "legacy-log": _cmd_legacy_log,
    "rag-slices": _cmd_rag_slices,
}


def _dispatch(cmd: str, argv: list[str]) -> int:
    handler = _COMMANDS.get(cmd)
    if handler is None:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    return handler(argv)


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
