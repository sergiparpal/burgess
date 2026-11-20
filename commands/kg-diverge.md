---
description: Turn any creative brief into a diverse, non-cliché slate of ideas — pure divergence, no graph and no source document required. Cliché map → mechanism-first generation → engine geometry (MAP-Elites, k-NN novelty, DPP slate, anti-collapse monitor) → the user pins/discards in chat. Pinned ideas can later be materialized into the hypothesized lane.
argument-hint: "<brief> [domain-template] [reach: conservative|balanced|wild]"
allowed-tools: Read, mcp__plugin_burgess_burgess__kg_diverge_init, mcp__plugin_burgess_burgess__kg_diverge_ingest, mcp__plugin_burgess_burgess__kg_diverge_remember, mcp__plugin_burgess_burgess__kg_diverge_parents, mcp__plugin_burgess_burgess__kg_diverge_metrics, mcp__plugin_burgess_burgess__kg_diverge_recall, mcp__plugin_burgess_burgess__kg_diverge_materialize, mcp__plugin_burgess_burgess__kg_diverge_export
---

# /burgess:kg-diverge — standalone divergence (FUSION Stage 3)

Brief: $ARGUMENTS

You amplify creativity by pairing **your** generation + judgment with the plugin's local
**divergence engine**, which owns the anti-convergence math. Diversity is decoupled from
quality: geometry (the engine) decides what is *new*; you only filter what is *valid/on-brief*
and rank *within* a niche. Never let the judge pick the final slate. **The user is the real
selector.** Nothing here needs — or touches — the knowledge graph: no sources, no canon, no
verdicts (ideas can enter the graph later, only through the propose lane, and only if the
user materializes their pins).

The engine runs inside the plugin's MCP server as the `kg_diverge_*` tools. There is no
interpreter to locate and no hand-off files to write — the tools take JSON directly. If a
`kg_diverge_*` tool errors with a provisioning message (engine deps still installing), relay
it verbatim and wait; convergence tools are unaffected by design (I9).

**Files: Read tool only, never Bash.** The references this command names are plugin files at fixed
paths: `${CLAUDE_PLUGIN_ROOT}/skills/burgess/references/operators.md`, `axis_inference.md` and
`judge_rubric.md` in that same folder, and the domain templates in `${CLAUDE_PLUGIN_ROOT}/pack/domains/`
and `${CLAUDE_PLUGIN_ROOT}/pack/domains/examples/`. Open them with the Read tool at those paths; there is
nothing to search for. A Bash read outside the project asks the user for permission: in the 2026-11-19
field run seven of them (find, cat, sed on these files and on the session state) waited 96 minutes for
approval, most of it before the first round. The session's own state needs no file at all:
`kg_diverge_init` returns the resolved axes, `kg_diverge_recall` returns them with the session id,
the seed, the pins, the discards and the comparisons, and `kg_diverge_export` writes every idea of the
session to a file for the user (step 11). Never read `.kg/diverge/` files.

## Reach — how far out (the divergence dial)

Maximum divergence is not always what the user wants: it produces extravagant, and
sometimes absurd or cryptic, ideas. **Reach** is the tempered middle band between
greatest divergence and collapse-to-the-mean. It caps divergence in *degree*
(`boldness`) and biases the operator mix and `feasibility` lean — it **never** caps
divergence in *kind* (the `mechanism` axis always spreads maximally, so every slate
is still made of genuinely different approaches).

| reach | `boldness` band | `feasibility` lean | operators | feel |
| --- | --- | --- | --- | --- |
| `conservative` | `[0, 0.5]` | high (`0.6`–`1.0`) | recombinative | spirited but buildable |
| **`balanced`** (default) | `[0, 0.75]` | spread `[0.2, 1.0]` | mixed | novel, still coherent |
| `wild` | `[0, 1]` | full `[0, 1]` | far-reaching welcome | maximal divergence (prior behavior) |

Pick the reach from the user's phrasing if they gave one (in `$ARGUMENTS` or the
brief's tone); otherwise **default to `balanced`** and mention it in the same
one-line confirm as the axes (step 2) — e.g. "Running at *balanced* reach; say
*wild* for further-out or *conservative* for safer." The user can change it any
round. Reach is a language-layer directive you apply when assigning descriptors and
choosing operators — the engine is unchanged; it still only measures dispersion over
what you submit (I5). Coherence (the judge's validity gate) is enforced at **every**
reach — `wild` means further-out, never incoherent.

## One session

1. **Project + session.** Choose a short `PROJECT` slug for this brief (e.g. `"cold-brew-launch"`)
   and ONE session id for this chat session (e.g. `"sess-<date>-<short-random>"`). State lives
   project-locally under `.kg/diverge/<project>/`. Session rule (I10): the geometry archive is
   ephemeral — passing a NEW session id wipes it; re-passing the SAME id within this chat resumes
   it. Pins and discards always survive across sessions.

2. **Resolve axes** (diversity is only meaningful relative to descriptor axes). Cascade:
   - the user named a domain that ships as a template (`${CLAUDE_PLUGIN_ROOT}/pack/domains/*.yaml` or
     `${CLAUDE_PLUGIN_ROOT}/pack/domains/examples/*.yaml` — e.g. `generic`, `marketing`,
     `product_features`, `research_hypotheses`): pass its name as `axes`;
   - else **infer** 4–6 descriptor axes from the brief per
     `${CLAUDE_PLUGIN_ROOT}/skills/burgess/references/axis_inference.md`
     (exactly one `open` axis marked `primary_novelty: true` — the mechanism carrier) and
     **confirm them with ONE short question** the user can accept or tweak; pass the result
     as an inline `axes` dict;
   - else omit `axes` — the engine prefers the pack's `divergence:` section, falling back to
     the neutral generic template.

   Then call `kg_diverge_init(project, axes, session)` and `kg_diverge_recall(project)` —
   recall returns prior pins/discards/comparisons for this brief so you generate AWAY from
   what the user already discarded and FROM what they pinned. `kg_diverge_init` returns the
   resolved `axes` (names, types, ranges, which one is the open axis) and
   `candidates_per_generation`: write every descriptor with exactly those axis names. A template's
   comments say what each axis means; if you want them, Read the template at its path above.

3. **Map the clichés (anti-cliché directive), before generating.** Enumerate the **~6 most
   obvious/cliché answers** to *this* brief. Split: **O_train** (first ~3 — keep in view,
   deliberately generate *away* from them) and **O_test** (last ~3 — set aside; never look at
   them while generating, never optimize toward them). After a slate is presented you *may*
   report each idea's distance to the held-out **O_test** as advisory originality — never
   validate against O_train (Goodhart trap), and never let any originality number pick or rank
   the slate. Caveat honestly: "obvious" is your notion of cliché; this hedges cliché, it does
   not guarantee novelty against the world.

4. **Generate candidates yourself, mechanism-first**, using
   `${CLAUDE_PLUGIN_ROOT}/skills/burgess/references/operators.md`
   (apply several DIFFERENT operators per round — biased by the reach dial: recombinative
   under `conservative`, mixed under `balanced`, far-reaching welcome under `wild`):
   - *Layer 1 — mechanism first.* Before writing a candidate's `text`, choose its
     **mechanism** (the open-axis value): the core "how it works" in a few words, far from
     (a) O_train's mechanisms, (b) mechanisms already used this round or in the archive.
     **Same mechanism = same idea.** Reach never narrows this — mechanism variety is
     always maximal.
   - *Layer 2 — surface second.* Write the `text` that expresses that mechanism, and make
     it self-explanatory: a reader should grasp *how it works* without a footnote.
   - *Layer 3 — the explanation.* Write the `explanation` you will show the user in step 7: two or
     three plain lines on how it works in practice, with one concrete example (for a hypothesis, how
     it would be tested). Send it in the candidate. The engine keeps it with the idea, returns it when
     the idea comes back on a later slate, and prints it in the export (step 11). It never embeds it,
     so it cannot move the idea. If you cannot write it, the idea is incoherent: cut it at step 5. In
     the 2026-11-19 field run the explanations lived only in the conversation, and the export had to
     dig those of the early rounds out of the transcript.
   - **Descriptor discipline:** niche placement runs on YOUR descriptor words. No two
     candidates share a `mechanism` string unless they genuinely share a mechanism; spread
     each continuous axis to the extremes **of its reach band** (`boldness` within the band
     for this reach; honest `feasibility` across its lean) rather than clustering in the
     middle; make each axis value meaningfully distinct. See `operators.md` →
     "Descriptor discipline".

5. **Prefilter** with `${CLAUDE_PLUGIN_ROOT}/skills/burgess/references/judge_rubric.md`: drop ONLY
   invalid/off-brief candidates. NEVER judge novelty here. You may attach a within-niche `fitness`
   (0–1) — the engine clips its influence to a bounded multiplier ([0.7, 1.3] at weight 0.3); you
   may NOT use it to cut variety. If you find yourself dropping more than ~40% of a round, you are
   over-filtering.

6. **Ingest.** Call `kg_diverge_ingest(project, candidates, axes, seed)` with the survivors:

   ```json
   [{"id": "c1", "text": "the idea, one or two sentences",
     "explanation": "two or three plain lines: how it works in practice, and one concrete example",
     "descriptor": {"angle": "…", "scope": "…", "form": "…", "boldness": 0.9,
                     "feasibility": 0.4, "mechanism": "the core how, a few words"},
     "fitness": 0.8,
     "genealogy": {"operator_id": "analogy", "parents": []}}]
   ```

   Give every candidate a fresh unique `id` (`c<round><letter>` works). Use the same `axes`
   argument you initialized with, and one integer `seed` per session for reproducibility.
   **Populate every continuous axis your resolved `axes` declares** — including `feasibility`
   (0 = far-fetched, 1 = buildable) when present. Omitting a continuous value is not neutral: the engine
   bins a missing value to the middle, so an unpopulated `feasibility` forfeits the coverage guarantee
   (one buildable elite per bin) that the axis exists to provide. Skip it only if your `axes` truly
   omit it (e.g. names/taglines, where "buildable" is meaningless).

7. **Present the returned `slate`** — for each idea: its text, its `explanation` (how it works
   in practice, with a concrete example, so a bold idea reads as clear, not cryptic), mechanism
   label, niche `coords`, and a one-line *why-picked* (which niche it holds + what its `novelty`
   says). Present the explanation you ingested, so what the user reads is what the export keeps.
   Field honesty: `novelty` is mean k-NN distance to THIS SESSION's own ideas — a variety
   proxy, not originality vs the world; `mechanism_novelty` is the same for its mechanism.
   Report them as such.

   **Earlier ideas on the slate.** The engine picks the slate from every idea in the archive, not only this
   round's, so a slate often brings earlier ideas back. Mark each with its round, summarize it in a line
   (its slate item carries the explanation it was ingested with), and explain in full only the new ones. A
   repeat is no reason to discard: a discard is negative memory (never slated again, never a parent), so
   offer it for an idea the user finds wrong, never as a way to stop one from coming back. In the
   2026-11-19 field run the session suggested discards for exactly that («si no quieres verla más», «que
   ya ha salido tres veces»), and one of those ideas was the parent of two later ideas.

   **Then the rest of this round.** After the slate, list every other idea you ingested this round that the
   slate left out, by id, in two or three plain lines each: what it claims, and one concrete example.
   Those lines are the explanation you ingested it with. Not a table of one-liners, and not ideas from
   earlier rounds. The slate is the engine's diverse pick, not a filter on what the user may keep: any
   idea can be pinned, and a pin makes it a parent. In the first field session (2026-11-16 to 11-19) round
   1 showed only its slate, and round 2 showed the rest as a one-line table. The user could not tell what
   those ideas were about («Así no sé de qué van»), and pinned one that had never been explained. Then:
   - ask only the returned `ask_pairs` as short A-vs-B questions. The answers do not move the slate or
     the parents: the engine only stops asking a pair already answered and tallies the answers for
     `kg_diverge_recall`. They reach the next round through you, when you generate. So a loser coming back
     on a later slate is expected; never explain it as comparisons weighing little, because the slate
     does not read them at all;
   - **explicitly invite pinning any idea** — "pin any idea of this round to keep exploring from,
     from the slate or the rest, not just A/B" (pins are the strongest, durable signal: always parents,
     recalled across sessions, and later materializable into the graph via /burgess:kg-generate's propose lane);
   - **offer the discard lever** — "drop any of these so we stop building on them?" (a discard
     is durable negative memory: never re-slated, never bred from; re-pinning un-discards).
     Discarding is the user's call, never yours.

8. **Record & continue.** For each answer/pin/discard call `kg_diverge_remember(project,
   event)` with `{"type":"pin","id":…}` / `{"type":"discard","id":…}` /
   `{"type":"comparison","winner":…,"loser":…}`. Then `kg_diverge_parents(project)` for
   diverse stepping stones (pins always kept, discards always excluded) and loop from step 4,
   or stop on the user's word.

   **After a compaction.** If the conversation was compacted between rounds, call
   `kg_diverge_recall(project)` before anything else: it returns this session's `session_id`, the
   `seed`, the resolved `axes`, the pins, the discards and the comparisons. Keep passing that seed.
   Do not call `kg_diverge_init` with another session id, which would wipe the archive, and do not read
   `.kg/diverge/` files: in the 2026-11-19 field run that read went through Bash and waited for the
   user's approval.

9. **React to the monitor** (the `mon` block in every ingest result — advisory notice to the
   user, never a question):
   - `collapsing: true` → say so briefly, then REGENERATE under diversity pressure
     automatically: new operators, forbid the crowded niches, demand distance from recent
     ideas. Never remove or bypass the monitor.
   - `under_generation: true` → you over-prefiltered; next round generate the full target and
     cut only invalid ideas, never the merely unusual.
   - `variety_eroding: true` (early warning: survivor novelty decaying faster while submits
     stay healthy) → push unused operators and *mechanism* variety next round.

10. **Session-end gap summary** (only when the axes set `engine: {gap_probe: true}` and ingest
    results carried a `surface_mechanism_gap` block): fetch `kg_diverge_metrics(project)` and
    give a short plain-language read of its `gap_log` across the whole session — varied in
    *approach* or only in *wording*? Measurement only; it never steers selection.

11. **Save the ideas** (when the user ends the session or asks to keep the ideas). Call
    `kg_diverge_export(project, brief)` once, with the brief in the user's own words. The engine
    writes every idea of this session to one Markdown file and returns its `path`; give the user
    that path. Each idea carries its text, its explanation, its descriptor, its operator and
    parents, the slates that showed it, and the user's pins, discards and comparisons. Never build
    the file yourself: no Bash, no script, no writing it out with Write, no reading `.kg/diverge/`
    or the transcript. In the 2026-11-19 field run the session did all of that, and the export
    waited about two hours on ten permission prompts. If the result's `unexplained` lists ids,
    those ideas were ingested without an explanation; say so, and do not rebuild them. The file
    lives in the brief's folder under `.kg/diverge/`, never in the project folder, because the
    project folder can be the source folder /burgess:kg-build reads. If the user wants the file
    somewhere else (their Downloads folder, say), offer to copy it there: a single copy command,
    which asks for permission once, and never a second copy of the content written by hand.

## Notes

- **Selftest** (engine correctness contract, offline): `python -m kg_engine.divergence selftest`
  from the plugin's engine venv — variety gate, DPP-beats-first-N, null check, collapse
  reversal. Also runs in the test suite (`tests/fusion/divergence/test_selftest_e2e.py`).
- **Importing old Cambrian state:** `python -m kg_engine.divergence import-cambrian
  --project <slug> [--from ~/.cambrian/<old-project>]` maps a Cambrian project's pins/
  discards/comparisons into `.kg/diverge/<slug>/` (best-effort, read-only on the source).
- **Materializing pins (explicit, kickoff Q5).** When the user asks to carry pinned ideas
  into the knowledge graph, call `kg_diverge_materialize(project[, candidate_ids])` — each
  pin becomes a node in the HYPOTHESIZED lane (`provenance=hypothesized`,
  `epistemic_state=unverified`, full `[diverge]` lineage in the body), routed exclusively
  through the propose door. Nothing enters the graph implicitly: only on the user's word,
  only pins, only during a session that still holds the idea's record (I10 — a stale pin is
  reported `skipped`; re-ingest it first). No source in the project? The ideas simply WAIT
  in the lane. Optional `edges` link materialized ideas to existing nodes (same boundary:
  forged verdicts stripped, text claims refused) — but they are **extras, not required**: a pin
  is materialized as a **node**, and that node is grounded on its own via `kg_ground(kind="node")`.
  A pin with **no wired edge is still fully groundable** — "no edge → can't be grounded" is false;
  grounding operates on nodes, not just edges. Materialized pins may be ground FIRST by
  /burgess:kg-ground (priority is ordering only — verdict-neutral by test). Grounding a materialized
  pin against an existing source will (correctly) leave it `unverified` — a novel idea has no
  in-source span yet — so it WAITS in the lane, recoverable, until you add supporting sources;
  a merely-unsupported (`rejected`) pin is **never** auto-discarded. Only when a pin is actively
  FALSIFIED (`failed`) does the next `kg_diverge_init`/`recall` fold it into this brief's
  **permanent** discards (unified negative memory, I8) and tell you. When a source is already
  configured, `kg_diverge_materialize` returns an `advisory` note that says exactly this.
- **Re-examinable discards (non-monotonic evidence).** The brief's negative memory is permanent
  on purpose — but evidence changes. When the **source set changes** after a pin was falsified,
  `kg_diverge_init`/`kg_diverge_recall` surface those `failed`-fated candidates under a
  `reexaminable_discards` list (`{candidate, fate:"failed", reason:"source-set-changed-since-judged"}`)
  — the divergence mirror of /burgess:kg-ground's re-examinable advisory. This is **surface-only**: it does
  NOT auto-un-seal anything. If the user decides a discarded idea deserves a second chance against the
  new source, call `kg_diverge_recall(project, reexamine=[candidate_ids])` — the **explicit** un-seal
  lever: it drops those candidates from the discards and clears their failure fate so they return to the
  proposal pool to be re-materialized / re-grounded. It never changes a graph verdict.
- Everything the engine computes is **advisory ordering** — embeddings measure dispersion,
  never truth (FUSION invariant I5).
