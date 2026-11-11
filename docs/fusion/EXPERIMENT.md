# EXPERIMENT.md — divergence.dpp default decision (FUSION_PLAN Stage 6, Decision Rule D1)

## Pre-declared protocol (written BEFORE any results were generated)

**Question.** Does presenting /kg-generate's hypothesized slate in advisory-DPP order with
geometry labels (`graph+generate+dpp`) lift blind ideation over the identical slate in donor
(score-ranked) order (`graph+generate`)? The candidate SET is identical by construction
(I5, snapshot-enforced) — only presentation differs.

**Harness convention (D1's escape clause).** The vendored harness defines no RNG seeds; its
convention is the **12 fixed ideation prompts** of `commands/kg-experiment.md` plus a blind
shuffle/de-shuffle protocol, scored deterministically by `kg_engine.harness.ideation`
(diversity, novelty, utility, unsupported_rate — n-gram measures vs the corpus). The
harness convention therefore replaces "N = 5 seeds" with **N = 12 prompts**; D1's per-seed
criteria map to per-prompt criteria, declared here before the run:

- **Per-prompt blind score** (the harness defines no single scalar, so one is pre-declared —
  the equal-weight, sign-corrected composite of the harness's four axes, each already in [0,1]):
  `score = diversity + novelty + utility − unsupported_rate`.
- **Flip `divergence.dpp` default to ON iff ALL of:**
  1. median per-prompt score(dpp arm) **strictly exceeds** median(baseline arm);
  2. the dpp arm **wins ≥ 10 of 12 prompts** (the nearest integer ≥ D1's 4-of-5 = 80% win rate);
  3. **no prompt regresses** by more than the noise band = **5% of the baseline median**
     (the harness defines no noise band, so D1's fallback applies).
- Otherwise the default **stays OFF** — and this file says so plainly. Either outcome ships:
  the structural fusion is complete regardless; only the flag's default is being decided.
- The pooled `harness ideation` table and its `dpp_verdict` are reported alongside as the
  harness's own read; the pre-declared rule above is what decides the flag.

**Setup.**
- Corpus: `examples/source.md` (the shipped standard demo corpus), verbatim.
- Graph: built by the executing agent as extractor — span-present edges written via `kg_write`
  (every span a verbatim source substring, boundary-verified), a majority grounded via
  `kg_ground`, two proposals actively FAILED so negative memory is populated, a couple left
  unverified. Exact counts in Results.
- Slates: one `kg_generate(mechanism="all", k=12, dpp=false)` and the same with `dpp=true`
  (identical sets asserted; only order/labels differ).
- Context packs per prompt: `kg_context(query=<prompt>, budget=2000)` grounded items rendered
  as opaque text; the arm block appends the slate — donor order for the baseline arm,
  advisory-DPP order + labels (bin, semantic novelty, cliché distance) for the dpp arm.
- Blinding: per prompt, the two blocks are shuffled with a seeded RNG (seed 7) and presented
  to a fresh generator subagent as "Context X / Context Y" — the generator never sees arm
  names, and the orchestrating script holds the mapping until de-shuffle. One idea
  (2–4 sentences) per (prompt × block).
- Wall-time cap: 60 minutes (D1); this run is far under it.

## Results (run 2026-07-02; wall time ≈ 4 minutes, far under the 60-minute cap)

**Graph built:** 33 items accepted from `examples/source.md` (12 span-present edges + their
nodes), 8 edges grounded, 2 proposals actively failed (negative memory populated), 2 left
unverified. **Slates:** `kg_generate(mechanism="all", k=12)` → 18 candidates, identical sets
flag off vs on (asserted); dpp advisory applied. **Blinding:** 12 fresh generator subagents,
one per prompt, seeded shuffle (seed 7; X held the dpp block in 8/12 prompts); no agent saw
an arm name; the mapping file stayed outside the blind task directory.

### Pooled harness table (`kg_engine.harness.ideation`)

| arm | n | diversity | novelty | utility | unsupported_rate |
|---|---|---|---|---|---|
| graph+generate | 12 | 0.970 | 0.946 | 0.533 | 0.160 |
| graph+generate+dpp | 12 | 0.964 | 0.961 | 0.433 | **0.347** |

Harness `dpp_verdict`: **"graph+generate+dpp did NOT clearly beat graph+generate"**
(novelty up slightly, but diversity and utility down and unsupported_rate more than
doubled — far beyond the 0.05 slack).

### Pre-declared per-prompt D1 rule

Per-prompt scalar (`diversity + novelty + utility − unsupported_rate`, declared above):

| | p0 | p1 | p2 | p3 | p4 | p5 | p6 | p7 | p8 | p9 | p10 | p11 | median |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline | 2.646 | 2.055 | 2.230 | 2.330 | 2.013 | 2.256 | 2.698 | 2.190 | 1.946 | 2.349 | 2.938 | 2.181 | **2.243** |
| dpp | 1.523 | 2.667 | 2.256 | 2.000 | 1.516 | 2.153 | 2.193 | 2.183 | 1.640 | 1.672 | 2.500 | 2.257 | **2.168** |

1. median(dpp) = 2.168 does **NOT** strictly exceed median(baseline) = 2.243 → criterion 1 fails.
2. dpp wins **3 / 12** prompts (needed ≥ 10) → criterion 2 fails.
3. Noise band = 5% × 2.243 = 0.112; prompts regressing beyond it: **7** (p0, p3, p4, p6, p8, p9, p10) → criterion 3 fails.

### Outcome

**All three D1 criteria fail → `divergence.dpp` default stays OFF.** The shipped
`pack/pack.yaml` keeps `dpp: false`; the arm, the flag, and the per-call override ship
regardless — only the default was being decided, and the measurement said no.

**Observed mechanism (honest read, not part of the rule):** the dpp arm's geometry labels
(niche bins, `semantic_novelty`, `cliche_distance` values) leaked into the generated ideas
as apparatus-jargon — several dpp-arm ideas cite the numbers themselves ("uniformly low
semantic_novelty (about 0.18-0.25)…"), which the harness correctly scores as unsupported
(those terms never appear in the source). The advisory ORDER may well be harmless-to-useful;
rendering the raw label VALUES into the generator's context measurably hurt. A future
refinement (out of scope for 0.1.0, noted in BLOCKERS.md as FUTURE): present geometry labels
to the human only, or strip numeric values from the generator-facing block — then re-run D1.

---

# Stage 8 method, 0.12.0 — grounded novelty, compared prompt by prompt

## Pre-declared protocol (written 2026-11-11, before the new measure was computed on any field run)

**Why the method changes.** Three field runs of `/kg-experiment` on the Windows corpus (eight Spanish
documents, 445,018 characters; 2026-11-10 and 2026-11-11) returned the same negative headline verdict. The
rule that produced it could not have returned another:
- **novelty** is distance from the source text. The control arm never sees the source and scored 0.91, 0.90
  and 0.90; the graph arm, whose context quotes the source verbatim, scored 0.71, 0.74 and 0.76. The 0.11.x
  rule required graph ≥ control on novelty.
- **the unsupported-claim guard** called a sentence supported when any of its first three long words
  occurred anywhere in the source. Its own probe let 140 of 143, 171 of 173 and 181 of 181 sentences with an
  invented word through.
- **pooled single numbers** with a no-regression rule let differences of 0.003 decide a verdict.

**Question.** Given the same source and the same budget, does structured grounded context (`graph`) lead to
ideas that go further beyond the source while staying anchored to it than flat retrieval (`rag`) does? The
comparison with `control` (no context) is secondary. `graph+generate` is compared with `graph` (does the
hypothesized slate add to grounded context, Stage 9), and `graph+generate+dpp` with `graph+generate` (D1).

**Measures, per idea.** Deterministic and language-neutral.
- **novelty**: unchanged, 1 − the share of the idea's word trigrams that occur in the source.
- **support**:
  - A sentence's **key terms** are its words longer than five characters. Each is compared by its **stem**: accents
    and case folded, cut to the first six characters, each stem counted once. A sentence is judged when it has
    four or more words and at least two stems.
  - The weight of a stem is its IDF over the source's paragraphs, cut as `harness rag-slices` cuts them (a heading
    stays with its paragraph, none longer than 1,200 characters), in BM25 form:
    log((N − df + 0.5)/(df + 0.5) + 1). A stem that no paragraph holds has df = 0 and the highest weight.
  - The **coverage** of a judged sentence is the share of its stems' total weight held by stems the source
    contains. A word every paragraph has weighs little; a term the source lacks, such as an invented one, weighs
    the most.
  - An idea's support is the mean coverage of its judged sentences, and 0 when it has none.
- **grounded novelty** = novelty × support. An idea scores high only when it goes beyond the source's
  wording and its terms still meet in the source.
- Reported, in no verdict:
  - diversity;
  - utility (English markers; 0.11.8's caveat stays);
  - unsupported_rate: per idea, the share of judged sentences with coverage below 0.5, averaged over ideas.

**Revised before any field run was scored.** The first draft of this protocol, written the same morning,
required a sentence's key terms to meet in one paragraph, and compared whole words. Two things showed it
wrong, on the demo corpus and synthetic Spanish sentences only:
- **Inflections.** On a large source, one inflection the source does not use ("compararía" where it says
  "compara") took the highest weight and sank a sentence's coverage, so ideation text full of conditionals read
  as invented. Stems fix most of these.
- **One paragraph.** The requirement penalizes an idea that links concepts from two paragraphs, which is what a
  bridging idea does and what the graph arm exists to produce. Coverage is now over the whole source; the weight
  still makes an invented term cost the most.

No field output had been scored under either draft when this revision was made.

**Instrument check.** When the run has both `rag` and `control`, `rag`'s mean support must exceed
`control`'s by at least **0.10**. `rag` answers from source passages and `control` from nothing, so a
support measure that cannot tell them apart measures nothing on this source. When the check fails, every
verdict that uses grounded novelty reads "not measured", and a caveat says why. The probe stays as
information: the mean coverage drop when each judged sentence's first stem is replaced by a word that no
source holds.

**Decision rule, for a pair X vs Y.**
- Grounded novelty is compared prompt by prompt.
- A prompt is a **win** for X when X exceeds Y by more than 0.005, a **loss** when Y exceeds X by more than
  0.005, and a **tie** otherwise.
- X beats Y when its wins reach the one-sided sign test's 5 % level over all n prompts, ties counting
  against X: the smallest k with P(Bin(n, ½) ≥ k) ≤ 0.05. That is 10 of 12, as in D1.
- With fewer than five prompts no k qualifies, and the verdict says so.

**Pairs and verdict keys.**
- `verdict`: graph vs rag (the headline);
- `control_verdict`: graph vs control;
- `generate_verdict`: graph+generate vs graph;
- `dpp_verdict`: graph+generate+dpp vs graph+generate;
- `lightrag_verdict`: graph vs lightrag.

**Retroactive test.** The three saved field runs are scored with the rule exactly as written above, and the
results are recorded below whatever they are. The runs are 2026-11-10T16:58Z on 0.11.7, 2026-11-10T22:43Z on
0.11.8 and 2026-11-11T09:28Z on 0.11.10. In the first two, the read hook attached graph context to some of
the evaluator's reads (fixed in 0.11.9); the third is clean. No parameter above changes after the scores are
seen.

## Retroactive results (scored 2026-11-11 with the protocol above, unchanged)

The three saved field runs, scored with the engine of 0.12.0 on copies of the outputs and the eight documents.
Grounded novelty is shown as **gn**.

| run | arm | novelty | support | gn |
|---|---|---|---|---|
| 1 (0.11.7) | control | 0.917 | 0.923 | 0.846 |
| | graph | 0.717 | 0.933 | 0.669 |
| | graph+generate | 0.831 | 0.911 | 0.757 |
| | graph+generate+dpp | 0.830 | 0.953 | 0.791 |
| | rag | 0.624 | 0.971 | 0.606 |
| 2 (0.11.8) | control | 0.900 | 0.931 | 0.837 |
| | graph | 0.738 | 0.962 | 0.708 |
| | graph+generate | 0.816 | 0.928 | 0.757 |
| | graph+generate+dpp | 0.841 | 0.924 | 0.776 |
| | rag | 0.682 | 0.953 | 0.650 |
| 3 (0.11.10, clean) | control | 0.903 | 0.937 | 0.845 |
| | graph | 0.758 | 0.879 | 0.666 |
| | graph+generate | 0.823 | 0.904 | 0.744 |
| | graph+generate+dpp | 0.818 | 0.920 | 0.751 |
| | rag | 0.638 | 0.986 | 0.628 |

**Instrument check: failed in all three runs.**
- rag's support exceeded control's by 0.048, 0.022 and 0.049, below the 0.10 required.
- Every verdict therefore reads "not measured: support does not separate rag from control on this source".
- The measure does respond to invention: replacing a sentence's first key term with an invented word cost it
  0.155, 0.159 and 0.162 of support on average.
- But the control arm, writing from nothing, used the corpus's own vocabulary almost everywhere: 92-94 % of its
  key-term weight. On eight documents, 445,018 characters, about the topics the prompts name, lexical support
  cannot tell an idea written from the source from one written without it.

**Prompt-by-prompt counts.** These are recorded for completeness and are not verdicts, because the check
failed:

| pair | run 1 | run 2 | run 3 |
|---|---|---|---|
| graph vs rag | 9 of 12 | 7 of 12 | 8 of 12 |
| graph vs control | 1 of 12 | 0 of 12 | 0 of 12 |
| graph+generate vs graph | 10 of 12 | 6 of 12 | 12 of 12 |
| graph+generate+dpp vs graph+generate | 8 of 12 | 8 of 12 | 4 of 12 |

**Reading.** On this corpus, no lexical measure the harness has can carry a verdict. Support passes the
probe and fails the known-groups check, so what remains is novelty, which favors whoever saw the least source.
The method now says "not measured" where 0.11.x said "did NOT clearly beat". The next instrument would be the
blinded pairwise judge (option D of the 2026-11-11 proposal), or a source whose vocabulary an uninformed
writer does not already share. A local-co-occurrence variant of support was rejected before any scoring (see
the revision above). Testing it now would mean a new protocol, declared before new runs, not a re-scoring of
these.

---

# Option D — a blind judge per prompt (pilot protocol, pre-declared 2026-11-11)

Written before any packet was built or any judgment made. It is applied first to the ideas already saved from
the fourth field run (2026-11-11T11:17Z, plugin 0.12.0, clean blinding), as a pilot. Whether the judge ships
in `/kg-experiment` depends on the pilot passing the validity checks below.

**Why.** On the Windows corpus the 0.12.0 lexical method cannot carry a verdict. Its support check failed on all
four runs (gaps 0.022–0.049 against 0.10 required), because an uninformed writer already uses the corpus's
vocabulary. What the experiment asks, whether an idea is new, supported and useful, needs a reader.

**Material per prompt** (12 prompts; one packet each):
- the prompt;
- six items labelled A–F: the five arms' ideas (control, graph, graph+generate, graph+generate+dpp, rag) and
  one **decoy**;
- for each item, its **evidence**: the source passages that `harness rag-slices`' BM25 returns for the
  item's own text, within 600 tokens. Every item gets the same treatment, whichever arm wrote it.

**The decoy.** For each prompt it is a plausible idea of two to four sentences, in the corpus's language and in
the arms' register. Its central support is invented: it cites a study, an organisation or a figure that the
source does not contain. In the pilot the orchestrating session writes the decoys, and checks that every
invented name is absent from the source. Decoys take part in no arm comparison.

**Order.** The six items follow a seeded permutation (seed 7, as in D1), rotated by one position per prompt.
Over the 12 prompts every item therefore takes every position exactly twice. The labels follow position. The
mapping from labels to arms stays outside the judges' reach.

**The judge.** Each prompt gets a fresh subagent that knows nothing of the arms, the graph or the experiment's
hypothesis. It reads only its packet and writes one JSON verdict:
- for every item, three integer scores from 1 to 5:
  - **grounded**: its factual claims hold in its evidence. Claims the evidence lacks or contradicts lower it;
    a claim stated as a hypothesis does not.
  - **novel**: it proposes something its evidence does not already say, such as a new connection, mechanism or
    test. A restatement scores low.
  - **useful**: it is specific enough to test or apply. Vague ideas score low.
- a strict **ranking** of all six items, best first. An item whose support is invented may not rank above one
  whose support holds.

**Aggregation**, deterministic, from the recorded verdicts:
- the decoy is removed from each ranking;
- for each pre-declared pair (graph vs rag, graph vs control, graph+generate vs graph, graph+generate+dpp vs
  graph+generate), a prompt is a win for X when the judge ranked X above Y;
- X beats Y at 10 of 12 prompts, the one-sided sign test at 5 % as in 0.12.0.

**Validity checks.** If either fails, every verdict reads "not measured".
- **V1:** the decoy's grounded score is the lowest of the six (ties allowed) in at least 10 of the 12 prompts.
- **V2:** the five arm ideas' mean grounded score exceeds the decoys' mean by at least 1.0.

**Reported, deciding nothing:**
- the mean scores per arm and criterion, and the mean rank;
- the win rate by position, for position bias;
- the mean length of each arm's ideas, since length can sway a judge.

**Known limits.**
- The judge is the model that wrote the ideas. It favours no arm by itself, but it may reward a rigorous tone.
- The run-4 ideas still carry style marks of their arm ("la arista …", "candidato sin verificar"), so the pilot
  is less blind than a run written under a neutral-style rule.
- One run is one sample.

No parameter above changes after the verdicts are read.

## Pilot results (2026-11-11, run 4 judged by 12 blind judges)

**Validity: passed.**
- **V1:** the decoy had the lowest grounded score in 12 of 12 prompts.
- **V2:** the arm ideas' mean grounded score exceeded the decoys' by 2.57: 3.57 against 1.00.
- The judges caught every invented study.

**Verdicts by the declared rule** (wins out of 12, 10 needed): none decided.

| pair | wins | losses | verdict |
|---|---|---|---|
| graph vs rag | 3 | 9 | did NOT clearly beat |
| graph vs control | 5 | 7 | did NOT clearly beat |
| graph+generate vs graph | 4 | 8 | did NOT clearly beat |
| graph+generate+dpp vs graph+generate | 7 | 5 | did NOT clearly beat |

| arm | grounded | novel | useful | mean rank of 6 | words |
|---|---|---|---|---|---|
| control | 4.33 | 2.83 | 3.08 | 2.58 | 58 |
| graph | 3.33 | 2.75 | 3.00 | 3.17 | 100 |
| graph+generate | 3.08 | 3.08 | 2.92 | 3.58 | 109 |
| graph+generate+dpp | 3.25 | 3.00 | 2.92 | 3.08 | 102 |
| rag | 3.83 | 2.92 | 3.67 | 2.58 | 94 |
| decoy | 1.00 | 3.00 | 3.00 | 6.00 | 63 |

Position balance: first place went to labels A–F 2, 2, 4, 2, 1 and 1 times.

**A confound the validity checks did not cover.** The judges' notes name what lowered the graph-based ideas'
grounded scores, and it splits in two:
- **Real facts outside the evidence window.** The notes cite "AUROC de 0,65", Sonar's 32 %, 19,8 %, HAL,
  Faros's +154 %, Czerwonka and Uber's 70 % as absent from an idea's evidence. Every one of them is in the
  source. They were outside the 600 tokens of passages that BM25 returned for the idea's own text. An idea
  that combines facts from several documents, which is what the graph context invites, gets credit for few of
  them.
- **Statements about the graph itself,** such as "59 aristas" or candidate edges. No source passage can support
  them. This is the style leak the protocol anticipated, and a neutral-style rule for the evaluator would
  remove it.

V1 checks that the judge rejects invented support. Nothing checks that it credits real support drawn from far
in the source. So the pilot's verdicts measure "claims supported by the idea's nearest passages", which
penalizes fact-dense, cross-document ideas.

**Decision, per this protocol.** The judge does not ship as specified. A revised protocol, piloted anew, would
need:
- evidence retrieved per claim or per sentence, not per idea;
- a positive control: an item whose real support is spread across documents, which the judge must credit;
- the neutral-style rule in the evaluator.

The cost was also higher than estimated: about 65,000 tokens per judge, against the 6,000–7,000 planned.
Most of it was a general-purpose subagent's own overhead.
