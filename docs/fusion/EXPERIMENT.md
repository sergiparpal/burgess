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

---

# Option D, second pilot — evidence per claim and a positive control (pre-declared 2026-11-11)

Written before any packet of this pilot was built or any judgment made. It revises the first pilot on the two
points its judges' notes exposed, and it judges the same material: the fourth field run's ideas (2026-11-11T11:17Z,
plugin 0.12.0). The arms' style marks remain ("59 aristas", candidate edges). A neutral-style rule needs a new
run, and it is left for a later pilot if this one shows the coverage confound gone.

**What changes from the first pilot.**
- **Evidence per claim.** Each sentence of four or more words in an item gets its own evidence: the first two
  passages BM25 (`harness rag-slices`) returns for that sentence alone. Duplicates are removed, sentences are taken
  in order, and an item carries at most 6,000 characters of passages. An idea that combines facts from several
  documents now carries passages from each.
- **A positive control.** Each packet gains a seventh item. It is a plausible idea, written by the orchestrating
  session, whose support is real and spread over at least two source documents, each fact checked against the
  source before judging. It takes part in no arm comparison.
- **Seven items, labelled A–G.** Their order is a seeded permutation (seed 7) rotated by one position per prompt,
  so every item takes every position once or twice over the 12 prompts.

**Revised before any judgment.** A check of the packets, made before any judge ran, found that per-sentence
evidence left a fact of 4 of the 12 positive controls out of their evidence. In each case the sentence chained two
or three facts from different places, and the two passages it got covered only one. Graph ideas are built the same
way. So, once and only once, evidence became per **clause**:
- sentences are split at commas, semicolons and colons, and every clause of four or more words is kept;
- retrieval runs in two rounds: each clause's best BM25 passage first, then each clause's second;
- duplicates are removed, and an item carries at most 8,000 characters.

With that rule all 12 controls carried every fact they cite.

**Unchanged.** The decoys (the first pilot's twelve), the judge's instructions and rubric (grounded, novel,
useful, 1–5, a strict ranking), one fresh judge per prompt, the pairs and the sign test (10 of 12).

**Validity checks.** If any fails, every verdict reads "not measured".
- **V1:** the decoy's grounded score is the lowest of the seven (ties allowed) in at least 10 of 12 prompts.
- **V2:** the five arm ideas' mean grounded score exceeds the decoys' mean by at least 1.0.
- **V3:** the positive control's grounded score is 4 or 5 in at least 10 of 12 prompts. It shows the judge credits
  real support that lies far apart in the source.

**Reading the notes.** Before the results are interpreted, each judge's notes are read for two things, and both
are counted:
- facts called unsupported that the source does contain;
- statements about the writer's materials (graph, edges, candidates).

Nothing is re-scored. The counts say whether the coverage confound is gone and how much the style leak still
weighs.

No parameter above changes after the verdicts are read.

## Second pilot results (2026-11-11, run 4 judged again, 12 blind judges)

**Validity: passed.**
- **V1:** the decoy had the lowest grounded score in 12 of 12 prompts.
- **V2:** the arm ideas' mean grounded score exceeded the decoys' by 2.90 (3.98 against 1.08).
- **V3:** the positive control scored 4 or 5 on grounded in 10 of 12 prompts, exactly the threshold.

**Verdicts by the declared rule** (wins out of 12, 10 needed): none decided.

| pair | wins | losses | first pilot |
|---|---|---|---|
| graph vs rag | 5 | 7 | 3 of 12 |
| graph vs control | 8 | 4 | 5 of 12 |
| graph+generate vs graph | 1 | 11 | 4 of 12 |
| graph+generate+dpp vs graph+generate | 5 | 7 | 7 of 12 |

| item | grounded | novel | useful | mean rank of 7 |
|---|---|---|---|---|
| control | 4.17 | 2.83 | 2.92 | 3.92 |
| graph | 4.25 | 3.00 | 3.17 | 2.58 |
| graph+generate | 3.33 | 3.00 | 2.92 | 4.33 |
| graph+generate+dpp | 3.58 | 2.92 | 2.92 | 4.17 |
| rag | 4.58 | 2.83 | 3.75 | 2.17 |
| positive control | 4.58 | 2.50 | 2.75 | 3.83 |
| decoy | 1.08 | 3.08 | 2.92 | 7.00 |

First place by position, A–G: 1, 1, 0, 4, 2, 3, 1.

**The notes, as declared.**
- **Facts called unsupported that the source contains:** 16 misses (one fact in one idea) in 5 of 12 packets (2, 5,
  7, 11 and 12): graph+generate 7, graph+generate+dpp 4, graph 3, rag 2, control none. The facts were the advice not
  to resample against an LLM judge as sole verifier, Sonar's 32 %, Time Warp's 11 %, RADAR as Meta's review system,
  Faros not isolating low risk, METR's noisy baseline, the N4 autonomy level (one judge took it for a graph label),
  uReview on all of Uber's PRs, the change of definition behind Uber's 70 %, and "caso longitudinal sin control".
  Several were stated through the graph ("el grafo registra que…", "candidatos sin verificar acercan…"), but the
  source holds them.
- **Statements about the writer's materials:** marked down in 7 of 12 packets (2, 3, 4, 6, 8, 9 and 10), in
  graph+generate's and graph+generate+dpp's ideas in all 7 and in graph's in 3. Examples are "el grafo guarda 59
  aristas fallidas o rechazadas", RADAR as "the highest-degree node", `reconciles_with` edges, compression and
  regrouping candidates, and "unverified seed candidate". No source passage can support them. In packet 12 the judge
  named such statements but did not mark them down, since the ideas flagged them as unverified.

On grounded, graph+generate scored below graph in 9 prompts. In 6 of them the notes cite statements about the graph
in its idea, and in the other 3 real facts its evidence lacked.

**The misses, rebuilt afterwards.** The missed items' evidence was rebuilt from the same inputs; nothing was
re-scored. In 11 of the 16 misses the supporting passage ranked third to eighth for one of the idea's clauses. In 4
it ranked below tenth for all of them, and in 1 it ranked second but the 8,000-character cap cut it. Two passages
per clause were the main limit.

**Reading.** The judge passes every declared check: it rejects invented support (V1), and in 10 of 12 prompts it
credits real support spread across documents (V3). The two positive controls that scored 3 (prompts 4 and 6) lost
points for the relation they drew, not for a cited fact. Between the two pilots, whose main difference is the
evidence, graph's mean grounded score rose from 3.33 to 4.25, second among the arms to rag's 4.58. The coverage
confound is smaller but not gone. Against the graph-based arms the notes now cite mostly the style leak, which only
a run written under a neutral-style rule can remove.

**Where this leaves the judge.** This protocol left the neutral-style pilot for when the coverage confound was gone.
It is smaller, not gone, so this pilot does not decide whether the judge ships. A third pilot would need a fresh run
written under a neutral-style rule and more evidence per clause. The alternative is to stop here.

The twelve judges used 80,526 to 98,575 tokens each, 1.03 million in all.

---

# Option D, third pilot — a run written in neutral style (pre-declared 2026-11-11)

Written before the run it judges exists. That run is the first `/kg-experiment` made with plugin 0.12.1, whose
evaluator writes every idea about the domain and never about its materials. The second pilot left both
confounds smaller but not gone. This pilot removes the style leak at its source and widens the evidence where
the coverage misses came from.

**Material.** The fifth field run: `/kg-experiment` with plugin 0.12.1, given run 4's prompt file as its
argument, so the twelve prompts, the decoys and the positive controls stay matched. If its prompts differ, no
judge runs.

**Neutrality check, before any packet is built.**
- **Scan.** Every arm idea is scanned for the graph's vocabulary:
  - "grafo", "arista", "nodo", "candidato", "sin verificar", "puente", "fundamentado" and their English forms;
  - the relation names (`confounded_by`, `reconciles_with`, `defends_against`, `collapses_into`) and `kg_`.
- **Reading.** Each match is read and classed as the domain's word, like control's "concepto puente" in run 4, or
  the apparatus's.
- **Threshold.** The run passes when at most 3 of the 60 arm ideas use the apparatus's.
- **Failure.** If it fails, no judge runs; the rule is revised and a new run made first.

On run 4, 38 ideas match, the 36 graph-based ones among them.

**Evidence per clause, wider.** Calibrated on run 4, whose misses are known, before this run exists:
- sentences are split at commas, semicolons and colons, and also before "y", "o", "pero", "mientras",
  "porque", "aunque" and "sino"; every clause of four or more words is kept;
- four rounds of BM25 passages: each clause's best, then each clause's second, third and fourth;
- then, for each figure or name of the item that the source holds and the evidence still lacks, the
  best-ranked passage containing it among its clauses' first twenty;
- duplicates are removed, and an item carries at most 20,000 characters.

On run 4, this rule carries:
- 15 of the 16 facts the second pilot's judges missed;
- 0.974 of the arm ideas' figures and names, against 0.819 under the second pilot's rule;
- every figure and name of the twelve positive controls.

A packet grows from about 43,000 characters to about 103,000.

**Positive controls.** The second pilot's twelve, two of them rephrased. The two that scored 3 (prompts 4 and
6) lost points for the relation they drew. Each now states it as a hypothesis to measure, and the sixth drops
the closing claim its judge found unsupported.

**Unchanged:**
- the decoys (the first pilot's twelve);
- seven items in the seed-7 order rotated per prompt;
- the judge's instructions and rubric, and one fresh judge per prompt;
- the pairs and the sign test (10 of 12);
- V1–V3, and the two counts read from the notes.

**What this pilot decides.** The judge is ready to ship in `/kg-experiment` when all of these hold:
- the neutrality check, V1, V2 and V3 pass;
- the notes name statements about the writer's materials in at most 1 packet;
- they name real facts called unsupported in at most 2 packets.

Otherwise it is not ready, and the record says which condition failed. Shipping stays a separate decision. With
packets this size, the twelve judges should cost about 1.5–2 million tokens, against 1.03 million in the second
pilot.

**Known limits.**
- Prompts 3, 4 and 5 ask what kind of relation would join two concepts; under the rule, the arms answer in
  plain words.
- The judge is still the model that wrote the ideas.
- One run is one sample.

No parameter above changes after the neutrality check is read, nor after the verdicts are.

## Third pilot results (2026-11-11, run 5 judged by 12 blind judges)

**Neutrality check: passed.** Six of the 60 arm ideas matched the scan, all of them "concepto puente", which
control and rag use as well: the domain's word. No idea used the apparatus's, against 36 of 60 in run 4.

**Validity: passed.**
- **V1:** the decoy had the lowest grounded score in 12 of 12 prompts.
- **V2:** the arm ideas' mean grounded score exceeded the decoys' by 3.60 (4.68 against 1.08).
- **V3:** the positive control scored 4 or 5 on grounded in 12 of 12 prompts.

**Verdicts by the declared rule** (wins out of 12, 10 needed): none decided.

| pair | wins | losses | second pilot |
|---|---|---|---|
| graph vs rag | 2 | 10 | 5 of 12 |
| graph vs control | 3 | 9 | 8 of 12 |
| graph+generate vs graph | 7 | 5 | 1 of 12 |
| graph+generate+dpp vs graph+generate | 3 | 9 | 5 of 12 |

Rag ranked above graph in 10 of 12 prompts, the count that would decide the pair the other way. The protocol
declares no verdict in that direction, so the count is reported, not decided.

| item | grounded | novel | useful | mean rank of 7 | words |
|---|---|---|---|---|---|
| control | 4.42 | 3.58 | 3.50 | 2.50 | 60 |
| graph | 4.67 | 2.33 | 2.92 | 4.25 | 110 |
| graph+generate | 4.75 | 3.08 | 2.92 | 3.58 | 115 |
| graph+generate+dpp | 4.58 | 3.00 | 2.75 | 4.33 | 110 |
| rag | 5.00 | 2.42 | 3.50 | 2.67 | 104 |
| positive control | 4.92 | 2.58 | 2.92 | 3.67 | |
| decoy | 1.08 | 3.08 | 2.83 | 7.00 | |

First place by position, A–G: 2, 2, 3, 1, 1, 2, 1.

**The notes, as declared** (read in full):
- **Statements about the writer's materials:** none, in any packet.
- **Facts called unsupported that the source contains:** in 2 packets.
  - In packet 3, a graph+generate idea's evidence lacked RADAR's 1/50 incident rate, which the source states.
  - In packet 1, a graph idea said Zalando's classifier approves changes. Its evidence described routing only,
    so the judge read it as a stretch. The source says elsewhere that Zalando approves 33 % of its PRs
    automatically.
- **Other claims called absent.** These are also absent from the source:
  - GEPA "converging on similar variants";
  - LLM-Modulo's hidden set;
  - Spotify's claim falling to RADAR and Zalando;
  - rewording as a test of overfitting;
  - an "ambigüedad" behind Spotify's claim.
- **Disputed readings.** The rest are readings the notes dispute:
  - an inference about canary deployment that the source does not draw;
  - an audit of harness tampering cited as evidence of overfitting.

**What the judges weighed.** With the style leak gone and the evidence wider, every arm is well grounded (4.42
to 5.00), so the ranking turns on novelty and usefulness.
- **Graph-based ideas:** the notes say again and again that they "mostly restate their evidence".
- **Control:** its ideas propose mechanisms the evidence does not hold, such as a patch that silences an
  exception so CI passes.
- **Rag:** its ideas tie their evidence to concrete checks.

**Decision, per this protocol.** Every condition holds:
- the neutrality check and V1–V3 pass;
- the notes name statements about the writer's materials in no packet;
- they name real facts called unsupported in 2 packets.

The judge is ready to ship in `/kg-experiment`. Whether to ship it is a separate decision.

**What its first clean reading says.** On this corpus, the graph-based arms do not produce better ideas than
flat retrieval or than no context. Graph won 2 of 12 prompts against rag and 3 of 12 against control.

**A limit this pilot does not test.** Novelty is judged against each idea's own evidence, retrieved for its own
words.
- An idea built from the source's facts finds them in its evidence and reads as a restatement.
- An idea phrased far from the source retrieves less of what the source already says, so it can read as newer
  than it is.

No item checks that. A negative control, the source restated in other words, would.

The twelve judges used 115,898 to 134,478 tokens each, 1.51 million in all.

---

# Option D, novelty and paraphrase — a calibration without judges (2026-11-11)

**The limit being tested.** The third pilot recorded a limit it did not test: novelty is judged against each
idea's own evidence, so an idea that restates the source in other words can read as new.

**The pilot drafted to test it.** A fourth pilot would have added a negative control: an eighth item that
restates the source in plain words, with no figure, no proper name and no run of five words shared with the
source. A check, V4, would have read its novel score.

**Why no judge ran.** Building its packets showed, before any judgment, that the evidence often lacks the
passage the control restates. So the evidence itself was measured instead.

**Calibration set.** Twelve negative controls, written first, and the 16 facts the second pilot's judges missed
on run 4.

| evidence rule | restated passages held (of 22) | controls holding all / some / none | run-4 misses carried (of 16) | packet, est. |
|---|---|---|---|---|
| H, the third pilot's | 15 | 7 / 2 / 3 | 15 | 122K |
| H + semantic neighbours | 16 | 7 / 3 / 2 | 15 | 139K |
| BM25 and semantic ranks fused | 10 | 5 / 2 / 5 | 12 | 118K |
| H + each sentence's and the whole idea's two best passages | 17 | 8 / 3 / 1 | 15 | 125K |
| H + a shared block of the prompt's own passages | 21 | 11 / 1 / 0 | 15 | 131K |
| both | 22 | 12 / 0 / 0 | 15 | 134K |

The semantic neighbours come from `potion-multilingual-128M`, the divergence engine's model. The shared block is
the run's rag-slices file for the prompt, the rag arm's own context.

**Test set.** Twelve fresh negative controls were written after the last rule was chosen. They restate other
claims of the source under the same constraints. Under that rule, of the 9 prompts the source answers:
- the evidence holds every restated passage in 4;
- it holds some of them in 1;
- it holds none in 4.

On the calibration set the same rule had held them all.

**Why.** The shared block holds the source's central answer to each prompt, which is what the first controls
restated. The fresh ones restate claims from elsewhere in the source. Of the 1,194 passages, the missing ones
rank between 4th and 108th under BM25, and between 9th and 142nd under the embedder. Each figure is the best rank
over a control's clauses, sentences and whole text. Carrying them would take tens of passages per idea.

**Conclusion.**
- Evidence retrieved for an idea's own words cannot reliably show the judge that the idea restates the source in
  other words.
- The improvement found on the calibration set does not carry to fresh controls.
- Novelty, as the judge measures it, can credit an idea for being phrased far from the source. The third pilot's
  order, which novelty moved, keeps that caveat.
- The fourth pilot was not run, and no judge tokens were spent.

**Ways forward, neither tried:**
- let the judge search the whole source before it scores novelty;
- drop novelty from the judge and read grounded and useful only.

---

# Option D ships in 0.13.0, without novelty

The blind judge becomes an opt-in step of `/kg-experiment`: `--judge`. It scores grounded and useful, never
novelty, for the reason the calibration above records.

**What a run does.**
- **Controls.** The command writes a decoy and a positive control per prompt. The positive control's facts come
  from the prompt's own rag passages.
- **Packets.** `harness judge-packets` checks both controls, then builds the packets with the third pilot's
  evidence rule and order.
- **Judges.** One fresh `kg-judge` subagent per prompt writes a verdict.
- **Aggregation.** `harness judge-aggregate` applies the pilots' rules.

**Validity, every run.** V1–V3 are checked on each run, so the two-criterion rubric needs no pilot of its own.
A run whose judge fails a check reads "not measured". When the checks pass, the judge's graph vs rag verdict is
the headline, and the lexical verdicts follow as a second reading.

**Checked before release.** On the field data, `judge.py` rebuilt the third pilot's packets byte for byte,
1,632,453 bytes in all. From that pilot's verdicts it reproduced:
- V1 12/12, V2 3.60 and V3 12/12;
- the four pairs: 2, 3, 7 and 3 of 12;
- the means for grounded and useful.

---

# What the blind agents could see (recorded 2026-11-11, fixed in 0.13.2)

Found while reviewing the first field run on 0.13.1. Two channels reached the agents that must work blind.
Neither told a judge which label was which arm: the mapping stayed in `private/` throughout.

**Claude Code's instruction files and memory index.** By default Claude Code hands every subagent the
CLAUDE.md files and its auto-memory index.

| who | started from | what reached them |
|---|---|---|
| pilots 1 and 2: the judges | the development session | the repository's CLAUDE.md, and a memory index describing the earlier field runs ("novelty vs source favors control") |
| pilot 3: the judges | the development session | the same, plus the first pilot's line: "decoy caught 12/12" |
| run 6 (0.13.0, judged): the 12 judges and both evaluator passes | the field session | "5 runs of the 5-arm ideation on the Spanish prompts…: graph never beat control; the support check fails here" |
| run 7 (0.13.1): the evaluator | the field session | "valid judge: graph loses to rag 3/9, beats control 11/1" |

**The judge's prompt.** 0.13.0's said "some were written with help, some without, and two are controls planted
to check you". The pilots told their judges only "You do not know who wrote the ideas or how, and you should
not try to guess."

**What the record shows.**
- No run-6 judge's notes mention arms, the study, controls or earlier results; their "control" is the domain's
  control group. The judges' reasoning is redacted, so an influence cannot be ruled out.
- A judge told about planted controls could pass V1 and V3 by looking for them. So run 6's V1 and V3 show
  less than the protocol meant them to, and so do pilot 3's, whose index named the decoy. Pilots 1 and 2 had no
  hint that a decoy existed, and their judges still gave it the lowest grounded score in 12 of 12 prompts.
- Run 6's graph vs control (11 of 12) runs against its index line ("graph never beat control"). Neither
  channel said anything about rag. Graph vs rag read 3 of 12.
- The evaluator writes every idea. One that has read an earlier verdict might write an arm differently, and
  nothing in the outputs could show it.

**Standing.** Run 6's verdicts stay as recorded, with these caveats. No run so far had blind agents that saw
nothing beyond their task.

**Fixed in 0.13.2.** The three measurement agents declare `omitClaudeMd: true`. Checked headless on Claude Code
2.1.316 and 2.1.321 (`DECISIONS.md`). The judge's prompt is back to the pilots' sentence.

**A clean replication, declared before it runs.** The next `--judge` run on 0.13.2 repeats run 6's method:
- the same twelve prompts, hence the same rag passages;
- the same evidence rule, seed, checks, pairs and thresholds.

It counts as clean when the evaluator's and the judges' transcripts carry no `instructions` attachment. Its
verdicts are reported as they come, whether or not they agree with run 6, and nothing is tuned after seeing
them.

## Clean replication results (2026-11-11, run 8 judged by 12 blind judges)

Run `20261111T222651Z`, on 0.13.2 and Claude Code 2.1.322.

**Clean, by the declared test.** None of the 13 measurement transcripts, the evaluator's and the twelve
judges', carries an `instructions` attachment. None of these agents received hook context or opened a memory
file. The judges ran on 0.13.2's prompt. Each read its whole packet and wrote its verdict, with Read and Write
only.

**The same method as run 6.**
- The same twelve prompts, and rag passages identical to run 6's byte for byte.
- `judge.py` has not changed since 0.13.0, so the evidence rule, seed, checks, pairs and thresholds are run 6's.
- The field session reused run 6's decoys and positive controls unchanged, where the command asks it to write
  them. `judge-packets` checked them again and passed them.

**Rebuilt from the run's files.** The repository's engine at 0.13.2 rebuilt the packets byte for byte (1,635,961
bytes), the label mapping, the lexical scores and the judges' aggregate.

**Evaluator order:** verified, on disk and in the evaluator's transcript.

**Validity: passed.**
- **V1:** the decoy had the lowest grounded score in 12 of 12 prompts.
- **V2:** the arm ideas' mean grounded score exceeded the decoys' by 3.37 (4.37 against 1.00).
- **V3:** the positive control scored 4 or 5 on grounded in 12 of 12 prompts.

**Verdicts by the declared rule** (wins out of 12, 10 needed):

| pair | wins | losses | run 6 |
|---|---|---|---|
| graph vs rag | 3 | 9 | 3 of 12 |
| graph vs control | 12 | 0 | 11 of 12 |
| graph+generate vs graph | 4 | 8 | 9 of 12 |
| graph+generate+dpp vs graph+generate | 2 | 10 | 2 of 12 |

- **Decided:** graph beat control, in 12 of 12 prompts. Run 6 decided the same pair in 11.
- **Graph vs rag:** 3 of 12 in both runs. Rag ranked above graph in 9 of 12, and the method declares no verdict
  in that direction.
- **Graph+generate vs graph:** run 6's 9 of 12, one short of a verdict, fell to 4.

| item | grounded | useful | mean rank of 7 | words |
|---|---|---|---|---|
| control | 3.58 | 3.08 | 5.33 | 77.2 |
| graph | 4.58 | 3.92 | 2.67 | 104.8 |
| graph+generate | 4.58 | 3.42 | 3.42 | 110.5 |
| graph+generate+dpp | 4.33 | 3.42 | 4.58 | 105.8 |
| rag | 4.75 | 4.08 | 2.00 | 102.3 |
| positive control | 4.92 | 3.75 | 3.00 | |
| decoy | 1.00 | 2.58 | 7.00 | |

First place by position, A–G: 1, 2, 1, 1, 2, 3, 2.

**Lexical reading: not measured**, as on every run of this corpus. Support does not separate rag from control:
0.959 against 0.907, a gap of 0.052 where the method needs 0.10.

**What the replication shows.**
- With blind agents that saw nothing beyond their task, the judge reads this corpus as run 6 did. The
  graph-based arm does not beat flat retrieval, and it does beat no context.
- Run 6's judges were told that controls were planted. Here judges told nothing about them still gave the same
  decoys the lowest grounded score, and the same positive controls 4 or more, in 12 of 12 prompts. So run 6's
  V1 and V3 did not rest on that hint.
- Run 6's lead for graph+generate does not replicate.
- Length is not controlled. Control's ideas are the shortest in both runs (77 and 71 words, against 100 to 115
  for the arms). Whether that moves the judges is not measured.

**Standing.** Run 8 is the first judged run whose blind agents saw nothing beyond their task. Its verdicts carry
none of the blinding caveats recorded above for run 6.

**Cost.** The twelve judges used 62,248 to 75,833 tokens each, 815,072 in all, counted as the pilots' were: each
judge's context at its last call, as Claude Code reports it. Run 6's judges used 827,891. The third pilot's
judges, general-purpose agents started from the development session, used 1.51 million. The cost the command
and the README state, about 1.5 million for 12 prompts, comes from them.
