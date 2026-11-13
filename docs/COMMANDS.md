# Burgess — Command Manual

The complete reference for Burgess's nine slash commands: what each one does, every argument it
accepts, what each argument option means, and a worked example per case.

This is the *user-facing* manual. For the machinery underneath it — the canon/derived split, the
write boundary, the divergence engine's internals — read [`ARCHITECTURE.md`](ARCHITECTURE.md).
For a narrative first session in plain language, read [`../TUTORIAL.md`](../TUTORIAL.md).

---

## Contents

| Command | One line | Needs a graph? |
| --- | --- | --- |
| [`/burgess:kg-diverge`](#burgesskg-diverge) | Diverge from a creative brief into a non-cliché idea slate | No — stands alone |
| [`/burgess:kg-build`](#burgesskg-build) | Extract a span-anchored graph from your source document(s) | No — it creates one |
| [`/burgess:kg-ground`](#burgesskg-ground) | Verdict the graph against the source — the **only** verdict path | Yes |
| [`/burgess:kg-generate`](#burgesskg-generate) | Propose new hypotheses from the graph's own structure | Yes |
| [`/burgess:kg-perturb`](#burgesskg-perturb) | Build a second construction and cross-generate against it | Yes |
| [`/burgess:kg-query`](#burgesskg-query) | Answer a question with provenance and falsification attached | Yes |
| [`/burgess:kg-view`](#burgesskg-view) | Render an offline `graph.html` + `GRAPH_REPORT.md` | Yes |
| [`/burgess:kg-eval`](#burgesskg-eval) | Measure extractor precision and grounding reliability | Yes |
| [`/burgess:kg-experiment`](#burgesskg-experiment) | Blind multi-arm test of whether the graph helps ideation | Yes |

The everyday flow is **diverge → build → ground → generate → query → view**. `/burgess:kg-perturb`,
`/burgess:kg-eval` and `/burgess:kg-experiment` are the optional "going further" commands.

---

## How arguments work

**Notation.** `<angle brackets>` mark a **required** argument. `[square brackets]` mark an
**optional** one, which falls back to a documented default.

**How a command reads what you type.** Every command receives everything you type after its name as
one line of text, and reads its arguments from that line. None of them relies on Claude Code's
numbered argument slots, whose numbering differs between Claude Code versions.

*Two arguments, in order.* `/burgess:kg-build` and `/burgess:kg-generate`. Quote an argument that contains spaces,
or let the command's own rule sort it out: `/burgess:kg-build` reads a trailing whole number as the wave size
and everything before it as the path (the engine applies that rule, in `kg_build_plan`), and
`/burgess:kg-generate` reads a whole number as `k` and the other word as the mechanism set.

*One path.* `/burgess:kg-perturb`, `/burgess:kg-eval` and `/burgess:kg-experiment` take a single path, and the whole line is
that path, so a path with spaces works with or without quotes. `/burgess:kg-view` takes one word.

*Whole-string.* `/burgess:kg-query`, `/burgess:kg-ground` and `/burgess:kg-diverge` consume everything you type as one
string. For `/burgess:kg-query` that string is your question; for `/burgess:kg-ground` it is a focus
filter; for `/burgess:kg-diverge` it is your brief, and the optional `domain-template` and `reach` are
*recognized within* that string rather than parsed out of fixed slots — so `wild` at the end of the
brief and "go wild with this" both work.

**Only two commands require an argument:** `/burgess:kg-query` needs a question, and `/burgess:kg-diverge` needs a
brief. The other seven run bare. (`/burgess:kg-build` run bare falls back to your configured `source_path`,
and stops with a clear message if you never configured one — it will never silently build something
you didn't ask for.)

## Two rules that govern every command

Everything below is an application of two invariants. They are worth internalizing before the
reference, because they explain why the arguments are shaped the way they are.

1. **Only `/burgess:kg-ground` produces a verdict.** `/burgess:kg-build`, `/burgess:kg-generate`, `/burgess:kg-perturb` and
   `/burgess:kg-diverge` all write into the graph, and everything they write arrives `unverified`. No
   command other than `/burgess:kg-ground` can mark anything trusted, and a payload that tries to assert a
   verdict is stripped at the write boundary. `/burgess:kg-query`, `/burgess:kg-view` and `/burgess:kg-eval` never write to
   the graph at all.
2. **Generation is never gatekept by a quality metric.** Candidates enter the graph offensively —
   the filter is applied afterwards, by `/burgess:kg-ground`. This is why no generative command takes a
   quality threshold argument: there is nowhere to put one.

Every claim in the graph carries three orthogonal axes, never collapsed into one score:

- **`provenance`** — `span-present` (a verbatim quote in your source backs it) · `inferred` (asserted
  without a quotable span) · `hypothesized` (a machine proposal, no span at all).
- **`authored_by`** — `deterministic` · `agent` · `human`.
- **`epistemic_state`** — `unverified` · `grounded` · `rejected` · `failed` · `obsolete`.

`rejected` and `failed` claims are **permanent negative memory**: never pruned, surfaced as
falsification counters, and used to block re-proposal of things the graph already refuted.

---

<a id="kg-diverge"></a>
## `/burgess:kg-diverge`

```
/burgess:kg-diverge <brief> [domain-template] [reach]
```

**What it does.** Turns a creative brief into a diverse, deliberately non-cliché slate of ideas.
Claude maps the obvious answers first and generates *away* from them, mechanism before surface;
the local divergence engine then measures dispersion — MAP-Elites niches, k-NN novelty, a DPP slate,
an anti-collapse monitor — and returns the spread. You pin and discard in chat; pinned ideas can
later be materialized into the graph as hypotheses.

This half of the plugin **stands alone**: no source document, no graph, no verdicts. Nothing enters
the knowledge graph unless you explicitly ask to materialize your pins.

**Where the state lives.** Project-local under `.kg/diverge/<project>/`. The geometry archive is
session-ephemeral (a new session id wipes it); **pins, discards and comparisons persist across
sessions** — they are the durable signal.

### Arguments

| Argument | Required | Accepted values | Default |
| --- | --- | --- | --- |
| `brief` | **Yes** | Free text — the creative problem | — |
| `domain-template` | No | `generic` · `marketing` · `product_features` · `research_hypotheses` | inferred from the brief |
| `reach` | No | `conservative` · `balanced` · `wild` | `balanced` |

### `domain-template` — what each option does

The template supplies the **descriptor axes** diversity is measured against. Diversity is only
meaningful relative to axes, so this choice shapes what "different" means for your slate.

| Value | Purpose |
| --- | --- |
| `generic` | The neutral, domain-agnostic axis set. Use when nothing else fits. |
| `marketing` | Axes tuned for campaigns, positioning, messaging. |
| `product_features` | Axes tuned for feature and product-direction ideation. |
| `research_hypotheses` | Axes tuned for research questions and hypotheses. |
| *(omitted)* | Claude infers 4–6 axes from your brief and **confirms them with one short question** before generating. Accept or tweak them. |

Templates live in `pack/domains/` and `pack/domains/examples/`; you can add your own `.yaml` there
and name it here.

### `reach` — what each option does

Maximum divergence is not always what you want: pushed all the way out it produces extravagant,
sometimes absurd or cryptic ideas. **Reach** is the tempered band between greatest divergence and
collapse-to-the-mean. It caps divergence in *degree* (how bold), and biases which operators and
feasibility levels get used. It **never** caps divergence in *kind* — the mechanism axis always
spreads maximally, so every slate is still made of genuinely different approaches.

| Value | `boldness` band | `feasibility` lean | Operators | Feel |
| --- | --- | --- | --- | --- |
| `conservative` | `[0, 0.5]` | high (`0.6`–`1.0`) | recombinative | spirited but buildable |
| **`balanced`** *(default)* | `[0, 0.75]` | spread `[0.2, 1.0]` | mixed | novel, still coherent |
| `wild` | `[0, 1]` | full `[0, 1]` | far-reaching welcome | maximal divergence |

The coherence gate runs at **every** reach: `wild` means further-out, never incoherent. You can
change reach at any round — just say so.

### Examples

Brief only — axes inferred, `balanced` reach:

```text
/burgess:kg-diverge Ways to get commuters to try our cold-brew without discounting it
```

Brief with a domain template:

```text
/burgess:kg-diverge Ways to get commuters to try our cold-brew without discounting it marketing
```

Brief with a reach dial — safer ideas you could ship this quarter:

```text
/burgess:kg-diverge Onboarding flow for a first-time budgeting app conservative
```

Brief with both, pushed all the way out:

```text
/burgess:kg-diverge Reduce single-use packaging in a grocery chain product_features wild
```

Because `/burgess:kg-diverge` reads the whole string, plain phrasing works too:

```text
/burgess:kg-diverge Name a research programme around forgetting in language models — go wild
```

Carrying results into the graph (after you have pinned ideas in chat) is a **separate, explicit
step** — just ask:

```text
Materialize my pins into the graph
```

Each pin becomes a node in the hypothesized lane (`provenance=hypothesized`,
`epistemic_state=unverified`) with its `[diverge]` lineage recorded in the body. Nothing enters
implicitly: only on your word, only pins. If your project has no source document, they simply wait
in the lane until you add one.

### Notes and honest limits

- `novelty` is k-NN distance to **this session's own ideas**; `originality` is distance to **Claude's
  own guess** at the clichés. Neither is novelty against prior art or the world.
- The cliché map hedges cliché; it does not guarantee freshness. "Obvious" is the model's notion of obvious.
- The judge can nudge ranking within a niche but cannot veto diversity. Bad ideas can still reach you
  — that is the point. **You are the selector.**
- A discard is durable negative memory: never re-slated, never bred from. Re-pinning un-discards it.
- If a materialized pin is later **falsified** by `/burgess:kg-ground`, it folds back into this brief's
  permanent discards. A merely *unsupported* pin stays recoverable in the lane.

---

<a id="kg-build"></a>
## `/burgess:kg-build`

```
/burgess:kg-build [subset] [wave_size]
/burgess:kg-build --leads [subset] [wave_size]
```

**What it does.** Reads your source document section by section, launching one extractor subagent
per section (in bounded parallel waves), and writes typed nodes and typed edges into the canon.
Every non-deterministic edge must carry a **verbatim span** copied from your source, or the write
boundary rejects it as fabrication.

**Everything it writes lands `unverified`.** `/burgess:kg-build` never asserts a verdict. It is **additive**:
run it again on another document of your source and the same graph grows.

**A section with nothing to extract is extracted once.** A list of sources, a glossary or a checklist states
no relation the pack's types can carry, so its extractor writes no claim from it. Since 0.14.0 the extractor
records that, and later builds skip the section until its text or the pack's types change; the plan counts
these sections apart (`sections_edgeless`). Through 0.13.6 every build launched an extractor for each of them
again, to read the same text and find nothing. Since 0.14.1 the extractor also records a section whose only
relations are edges the graph has already judged, from another section's span: the engine quarantines a claim
it already holds with a verdict, so a new read has nothing to add. Only the extractor that read a section
records it, and the engine refuses a record no read of the section stands behind. To have the recorded
sections extracted once more, delete `.kg-edgeless-sections.jsonl` from the project folder.

**It runs no shell commands.** The engine plans the build (`kg_build_plan`) and hands each extractor
its own section, already cut and scrubbed (`kg_section`). So the only thing `/burgess:kg-build` asks Claude Code
for is to launch its subagents, and in auto mode it no longer stops to ask your permission for shell
scripts. (Through 0.4.6 it ran a Bash step, and in auto mode Claude Code ignores a command's Bash
permission, so those commands could stop the build on a prompt.)

### Arguments

| Argument | Required | Accepted values | Default |
| --- | --- | --- | --- |
| `--leads` | No | The literal word, first on the line | build the sections no claim covers yet, except the ones an extraction found nothing in |
| `subset` | No | A file, a directory, or a glob of `.md` / `.txt` files **inside your configured `source_path`** | the whole configured source |
| `wave_size` | No | Integer `1`–`10` | the `extract_wave_size` option, else `6` |

### `--leads` — writing what `/burgess:kg-ground` found

When `/burgess:kg-ground` rejects a claim because its quoted text states another relation (a precondition filed
as evidence is an `enables` claim), or relates a broader or narrower concept than one of its nodes, the
grounder records the claim the text does state: a **lead**. A build skips every section that already has
claims, so it never writes them. `/burgess:kg-build --leads` does: one extractor per section that holds leads,
which writes those claims with the same quoted text and nothing else. They land `unverified`, and the
next `/burgess:kg-ground` judges them like any other. Each lead is written once. `/burgess:kg-ground`'s plan counts the
ones still waiting (`leads_pending`), and its report says when to run this.

### `subset` — what each form does

| Form | Purpose |
| --- | --- |
| *(omitted)* | Builds the whole `source_path` you configured when installing the plugin, resolved through the engine. If none is configured, the command **stops and tells you** — it will never silently build the bundled demo instead. |
| A single file | Build only that document. The common case once the source is a folder. |
| A directory | Build **every** `.md`/`.txt` file directly inside it (not recursive). |
| A glob | Build every matching file. |
| A bare file name | Build the configured file of that name, whichever folder the session was opened in. |

The subset only narrows the build. Every span is verified against the configured `source_path`, so a
file outside it would have every relationship rejected; the engine checks each file against the
configured source, and the command stops before launching anything for one it does not know. To build from
somewhere else, change `source_path` (see the README's configuration reference) and restart Claude
Code.

A name with spaces can go in quotes or not: a trailing whole number is read as the wave size and the
rest as the path, so `/burgess:kg-build research/Notas de campo.md 4` works. Quote a name that itself ends in
a number (`"research/capítulo 3"`), or that number is read as the wave size.

Spans are verified per file: an edge attributed to the wrong source file is rejected. Sections are
split at each file's **dominant heading level** — usually `##`, but a file whose only `##` is its
title and which carries several `###` subsections is split at `###` instead, so it never collapses
into one blob. Headings inside code blocks never count, a file with no heading is built as one
section, and the text before a file's first heading (usually its title and byline) is not extracted.

### `wave_size` — what the number does

How many section-extractor subagents run **concurrently** per wave. One section is always one
subagent (that isolation is what makes spans checkable rather than remembered); `wave_size` only
controls how many of those run at once.

- Precedence: explicit `wave_size` > the `extract_wave_size` plugin option > `6`.
- The value is clamped to **1–10**. Unset, non-numeric or `< 1` falls back to `6`; `> 10` clamps to `10`.
- Lower it (`1`–`2`) if you are rate-limited or want to watch the build step by step. Raise it
  (`8`–`10`) for a long document you want built quickly.

A lone number is the wave size for the whole source (`/burgess:kg-build 4`); before 0.5.0 it was read as a
subset that named no file. To change it for every build, set the `extract_wave_size` option instead.

### Examples

They assume your configured `source_path` is the folder `research/`.

Build all of it:

```text
/burgess:kg-build
```

Build one document:

```text
/burgess:kg-build research/theory-of-change.md
```

Build a matching set of its documents:

```text
/burgess:kg-build "research/chapter-*.md"
```

Build one document with a small wave, to watch it land section by section:

```text
/burgess:kg-build research/theory-of-change.md 2
```

Build one document whose name holds spaces:

```text
/burgess:kg-build research/Notas de campo.md
```

Build all of it at maximum parallelism:

```text
/burgess:kg-build 10
```

Write the leads the last `/burgess:kg-ground` recorded, then judge them:

```text
/burgess:kg-build --leads
/burgess:kg-ground
```

### Reading the report

The build starts by telling you what it is about to build: the files, the number of sections, and the
wave size and where it came from (your argument, the option, or the default). A section that already
holds extracted relationships, from an earlier or interrupted build, is skipped, so running the same
command again resumes it.

The build reports **dispositions** summed across every section:

| Disposition | Meaning |
| --- | --- |
| `ACCEPTED` | Written to the canon as `unverified`. |
| `DEMOTED` | The payload tried to assert a verdict or claim human authorship; the claim was stripped and the item written anyway. |
| `QUARANTINED` | A node or edge type your pack doesn't declare. Not an error — a pack-coverage gap. Extend `pack/pack.yaml`. |
| `REJECTED` | No supporting span, or a span not found in the named source (fabrication), or a truncated/invalid payload. |

A `REJECTED` reason of `no-supporting-span` or `span-not-in-source` is a *semantic* error and is not
retryable; `truncated-payload` or `schema-invalid` is a *transport* error and is.

---

<a id="kg-ground"></a>
## `/burgess:kg-ground`

```
/burgess:kg-ground [query-or-node-filter]
```

**What it does.** Drains the grounding queue — and this is the **only command in Burgess that can
mark anything trusted.** It re-reads each unverified claim's cited span against your real source,
rejects claims that are "true" only because they are vague (the generality confound), then turns an
adversarial grounder loose on the graph's hubs to construct the strongest counter-arguments it can.

What survives becomes `grounded`. What fails becomes **permanent negative memory** — never pruned,
never re-proposed, surfaced forever in the falsification counters.

**It runs no shell commands.** The engine plans the pass (`kg_ground_plan`): the queue, split into
batches, one grounder per batch, several at once (the `extract_wave_size` option). After any pins and
proposals, the claims the extractor marked weak go first, so a pass you stop early has judged them. Each grounder
fetches the evidence for its items itself (`kg_ground_item`): the claim, whether its quoted text is
still in your source, and the paragraph around it. Through 0.6.1 the orchestrator pulled the whole
queue at once, and on a large graph read it back with scripts, which in auto mode stopped on
permission prompts.

**Each hub is attacked once.** The adversarial grounder marks every counter-argument it writes with
the hub it attacks, and the next pass moves on to the next hubs down the list. When it finds nothing to
write against a hub, it records the attack and the question that would settle the hub, and that record
counts as the mark. A hub comes back once it gains a newly grounded claim, or when you name it as the
focus. Through 0.7.0 every pass attacked the same hubs again and left new unverified counter-arguments
behind, so the queue never emptied. Through 0.9.0 an attack that found nothing left no mark, so the plan
offered that hub to every later pass.

**The report lists leads.** When a claim is rejected because its quoted text states another relation (a
precondition filed as evidence is an `enables` claim), or relates a broader or narrower concept than one
of its nodes, the grounder records the claim the text does state on the rejected one. `/burgess:kg-build --leads`
writes those claims, and the next `/burgess:kg-ground` judges them. Through 0.8.1 nothing could write them:
`/burgess:kg-build` skips every section that already has claims.

**The grounders start without your notes.** Since 0.13.4 both grounders start without your CLAUDE.md files
and without Claude Code's memory index, which a subagent gets by default. A verdict rests on the claim's
source text and the grounder's contract, which carries the rules you have settled. A session that saves
its findings in memory would otherwise hand the next verdict what earlier passes or an eval thought of
the same claim.

Run it after every `/burgess:kg-build`, `/burgess:kg-generate` and `/burgess:kg-perturb`.

### Arguments

| Argument | Required | Accepted values | Default |
| --- | --- | --- | --- |
| `query-or-node-filter` | No | Free text — a topic or node name | the whole backlog |

### `query-or-node-filter` — what it does

| Form | Purpose |
| --- | --- |
| *(omitted)* | Drain the entire queue: every `unverified` relationship, and every `unverified` *proposed* node (a `/burgess:kg-diverge` pin or a generated idea), then attack the hubs. The nodes `/burgess:kg-build` extracts are not queued: the claims about them are their relationships. |
| A topic or node name | Focus the pass on that area of the graph, and use it to pick which hubs to attack. Useful when the backlog is large and you care about one region, or when you want a second adversarial pass over a concept you don't trust. |

The filter is an **ordering and scoping** device only. It never changes the evidence bar: verdict
logic is identical for filtered and unfiltered items.

### Examples

Drain the whole queue:

```text
/burgess:kg-ground
```

Ground only the claims and hubs around one concept:

```text
/burgess:kg-ground betweenness
```

Re-attack a concept you suspect is a vague hub earning spurious centrality:

```text
/burgess:kg-ground compression
```

Ground the fresh output of a generation pass:

```text
/burgess:kg-generate
/burgess:kg-ground
```

### What the verdicts mean

| Verdict | Meaning |
| --- | --- |
| `grounded` | The span verifies verbatim against the source **and** the relation is specific and falsifiable. |
| `rejected` | No supporting span, the span is not in the source, the span states another relation or relates a broader or narrower concept than one of the nodes, or the claim is "true" only because it is vague. Recoverable — add sources and it can be reconsidered. |
| `failed` | Actively **falsified** by a counter-argument. Permanent. |

Two advisories may surface, both strictly read-only — neither ever changes a verdict on its own:

- **Stale verdicts.** A grounded claim whose stored span no longer appears in the source, because you
  edited the source after it was judged. The claim is re-verified against the current text.
- **Re-examinable verdicts.** A `failed`/`rejected` claim that was judged against a source set which
  has since **changed**. Evidence is non-monotonic; these come back up for a second look, but only a
  deliberate re-grounding can change them.

Materialized `/burgess:kg-diverge` pins are grounded **first** — a purely ordering preference, since you
selected them by hand. A pin is a *node*, and routinely has no incident edge; it is still fully
groundable as a node. And because a pin is a genuinely novel idea, finding no span for it in your
current source is the **expected** outcome, not a failure: it is left `unverified`, waiting in the
lane, rather than spending a rejection on it.

If both grounders agree that two nodes may be the same concept, you get exactly one non-blocking
question (`Merge A and B? [y/N]`). The default is **N** — the pass proceeds without merging.

---

<a id="kg-generate"></a>
## `/burgess:kg-generate`

```
/burgess:kg-generate [mechanism-set] [k]
```

**What it does.** Turns the graph from a verification machine into an idea-generation machine. Seven
deterministic structural mechanisms read the graph's own shape and propose new claims: pairs that
should be connected, concepts that should exist, patterns that should transplant. The language layer
then phrases each proposal as one falsifiable sentence.

Everything lands in the **hypothesized lane** (`provenance=hypothesized`, `epistemic_state=unverified`,
**no span**) — visibly separate from grounded content, never presented as fact. Generation never
filters. `/burgess:kg-ground` is the filter, applied afterwards.

### Arguments

| Argument | Required | Accepted values | Default |
| --- | --- | --- | --- |
| `mechanism-set` | No | `default` · `all` · a single mechanism name | `default` |
| `k` | No | Integer — candidates to return | `10` |

### `mechanism-set` — what each option does

| Value | Runs | Purpose |
| --- | --- | --- |
| `default` | `bridge`, `seed`, `compression` | The three highest-yield mechanisms. What you want most of the time. |
| `all` | All seven | Widest sweep. Use on a mature graph, or when `default` returns nothing. |
| *a single name* | Just that one | When you know the shape of idea you are hunting for. |

The seven mechanisms, and what each one hunts:

| Mechanism | In `default`? | What it proposes |
| --- | --- | --- |
| `bridge` | Yes | Connections between two strong-but-separate hubs in different communities — the shortcut the graph lacked. |
| `seed` | Yes | Pairs that are **abnormally connectable for their distance** — the positive residual, not the raw product. |
| `compression` | Yes | New **nodes**, not edges: a concept that a dense cluster collapses into, but only when it genuinely saves description length and the cluster isn't vague. |
| `regroup` | `all` only | Re-partitions the graph at a different resolution and surfaces pairs that were invisible as bridges under the old partition. |
| `transplant` | `all` only | Imports a hub's reorganizing pattern into the community with the most capacity to absorb it, and names the hidden commitments that transfer with it. |
| `ensemble` | `all` only | Cross-construction bridges. Needs a second construction — that is what [`/burgess:kg-perturb`](#burgesskg-perturb) is for. Without one it degrades to `regroup` and says so. |
| `periphery` | `all` only | Sources candidates from the graph's **low-degree** nodes — the periphery every hub-seeking mechanism ignores. |

### `k` — what the number does

How many ranked candidates to return. Raise it when a mechanism surfaces nothing, or when you want a
wider slate to pin from. A whole number is read as `k` on its own, so `/burgess:kg-generate 20` asks the
default set for twenty candidates.

### Examples

The default three mechanisms, ten candidates:

```text
/burgess:kg-generate
```

All seven mechanisms:

```text
/burgess:kg-generate all
```

All seven, twenty-five candidates — a wide sweep of a mature graph:

```text
/burgess:kg-generate all 25
```

Only look for new concepts that a dense cluster should collapse into:

```text
/burgess:kg-generate compression
```

Hunt specifically in the neglected periphery, fifteen candidates:

```text
/burgess:kg-generate periphery 15
```

Then filter — always:

```text
/burgess:kg-ground
```

### The advisory DPP ordering

When your pack sets `divergence: {dpp: true}`, the **same** candidate set comes back reordered by
determinantal-point-process diversity, labelled with niche bins, semantic novelty and distance from
the graph's grounded "center". It is presentation only: same candidates, same scores, and grounding
downstream is **bit-identical** with the flag on or off. It is shipped **off** by default because
whether it actually lifts ideation was measured blind — see [`fusion/EXPERIMENT.md`](fusion/EXPERIMENT.md).

If `/burgess:kg-generate` reports `count == 0`, the structure surfaced nothing for those mechanisms. Try
`all`, a larger `k`, or `/burgess:kg-perturb`. A small graph is the usual cause.

---

<a id="kg-perturb"></a>
## `/burgess:kg-perturb`

```
/burgess:kg-perturb [second_source_or_graph_json]
```

**What it does.** Every other generator is *endo*: it elaborates the graph using the graph's own
structure, so it can only ever surface what the current construction already implies. `/burgess:kg-perturb`
is the *exo* move. It builds a **second, independent construction** of the same territory, then
cross-generates against it — surfacing bridges that exist in one construction's structure but not the
other's. Precisely the connections your graph's own dynamics would resist.

This is the only mechanism in Burgess that **attacks coverage** rather than elaborating within it.

Like `/burgess:kg-generate`, everything it emits is `hypothesized`/`unverified`, and `/burgess:kg-ground` is the filter.
The second construction is built **in-session**, through the same span-verified write boundary — no
API key and no extra dependencies required.

### Arguments

| Argument | Required | Accepted values | Default |
| --- | --- | --- | --- |
| `second_source_or_graph_json` | No | A path to a second source document, **or** a path to a pre-built `.json` graph | perturb in place |

### The argument's three modes

The command classifies the argument by its extension. There are exactly three behaviours:

| You pass | Mode | What happens |
| --- | --- | --- |
| A path ending in `.json` | `graph` | Cross-generates directly against that pre-built `graph.json`. The escape hatch when you already have a second construction on disk. |
| Any other path | `source` | An extractor builds that document into a **separately named alternate canon** under `.kg/constructions/<slug>/`, spans verified against *that* source. Your primary graph is untouched. Then cross-generation runs against it. |
| *(omitted)* | `degrade` | No second construction. The `ensemble` mechanism degrades to `regroup` — a re-partition of your existing graph. Still useful, but internal: it does not attack coverage. |

The `source` mode is the real one. Reach for a document that covers the same territory from a
different angle — a rival paper, a critic's essay, your own earlier draft.

### Examples

Perturb in place (degrades to a re-partition, and says so):

```text
/burgess:kg-perturb
```

Build a second construction from a rival account of the same territory:

```text
/burgess:kg-perturb papers/opposing-view.md
```

Cross against a graph you built earlier:

```text
/burgess:kg-perturb .kg-data/derived/graph.json
```

Then filter the imported bridges:

```text
/burgess:kg-ground
```

### The honest caveat

A second construction does **not** eliminate your blind spot. It **relocates** it. You trade your
construction's blind spots for a different set — and the bridges that survive *both* are the ones
worth grounding. The command states this every time it runs, and so should you when you report its
results.

`/burgess:kg-perturb` verifies that nothing leaked into your primary graph: it records the primary node and
edge counts before the build and re-reads them after. If the primary grew, the routing was dropped on
some section, and the command tells you rather than absorbing the leak silently.

---

<a id="kg-query"></a>
## `/burgess:kg-query`

```
/burgess:kg-query <question>
```

**What it does.** Answers your question **from the graph**, not from Claude's prior knowledge — and
surfaces the grounding state of every claim the answer leans on. Read-only: it cannot change the
graph, set a verdict, or invent an edge.

### Arguments

| Argument | Required | Accepted values | Default |
| --- | --- | --- | --- |
| `question` | **Yes** | Free text — the whole string is your question | — |

There are no options. The question can be factual ("what attacks the generality confound?"),
structural ("what connects compression and memory of failures?"), or open-ended ("what does this
graph actually know?").

### Examples

A factual question:

```text
/burgess:kg-query What grounds a compression?
```

A structural question — the answer will walk the graph:

```text
/burgess:kg-query What connects betweenness to the memory of failures?
```

A question about trust, not content:

```text
/burgess:kg-query Which claims about bridges are still unverified?
```

An open-ended orientation question:

```text
/burgess:kg-query What is this graph confident about, and where is it weakest?
```

> **Bound on structural chains.** When a question makes the command trace an associative chain between
> concepts, it walks **grounded edges only** and relates **at most 32 concepts per call**. The search costs
> one traversal per pair, so it is quadratic in that count; beyond the cap the engine refuses outright
> (`too many nodes: N (max 32)`) rather than stalling. A question that needs more concepts than that is
> really several narrower questions.

### Reading the answer

Every cited claim carries its axes inline:

```text
compression --grounds--> claim  [span-present / grounded]
  "A compression that survives specific attack is said to..."
```

The bracket is always `[<provenance> / <epistemic_state>]`, and a quoted span is a **literal
substring** of your source, never a paraphrase.

Three things the answer will always do:

1. **Lead with `grounded` claims.** Anything `unverified` is flagged as a *candidate, not a fact*.
   Hypothesized proposals appear only under an explicit "Hypotheses (unverified proposals)" heading,
   never mixed into the grounded answer.
2. **Report the falsification counters**, even when they are zero. A non-zero count means the graph
   remembers claims it refuted.
3. **Label the structural-bridge advisory as a heuristic.** Degree is the honest proxy for
   importance; specificity-weighted betweenness stays gated until validated. A vague node sits on
   many paths for empty reasons — the advisory is confounded by exactly the failure mode the graph
   exists to catch.

If the graph doesn't contain the answer, the command says so and points at what *is* there. It will
not fill the gap from memory.

---

<a id="kg-view"></a>
## `/burgess:kg-view`

```
/burgess:kg-view [html|report|all]
```

**What it does.** Renders two disposable, human-facing artifacts so you can *eyeball* the graph and
its grounding state. Read-only — it never writes the canon, never sets a verdict, never copies a span.
Both files are regenerable: treat them as a view, not a source of truth.

### Arguments

| Argument | Required | Accepted values | Default |
| --- | --- | --- | --- |
| `kind` | No | `html` · `report` · `all` | `all` |

### `kind` — what each option renders

| Value | Renders | Use it when |
| --- | --- | --- |
| `html` | `graph.html` only | You want to explore the graph visually. |
| `report` | `GRAPH_REPORT.md` only | You want numbers you can paste, diff, or commit. |
| `all` *(default)* | Both | Normal use. |

### Examples

Render both artifacts:

```text
/burgess:kg-view
```

Just the interactive visualization:

```text
/burgess:kg-view html
```

Just the Markdown report — handy after a grounding pass, to diff the counts:

```text
/burgess:kg-view report
```

### What the artifacts show

**`graph.html`** is a self-contained, fully offline force-directed visualization. Open it in any
browser; it needs no network and no dependencies. The three orthogonal axes are on three
**independent visual channels** — never collapsed into one "confidence" color:

| Axis | Channel | Encoding |
| --- | --- | --- |
| `epistemic_state` | Edge line | solid green = grounded · dashed = unverified · **red = failed/rejected** · dotted = hypothesized |
| `authored_by` | Node border | deterministic · agent · human |
| `provenance` | Node fill opacity | span-present (opaque) · inferred (mid) · hypothesized (faint) |

Node **size is degree** — the honest advisory. The gold **bridge highlight** is gate-aware: it uses
specificity-weighted betweenness only when that metric has earned promotion, otherwise the
structural-bridge advisory. Size is never the bridge metric, so the generality confound is never
smuggled into it.

Failed and rejected edges are **drawn but exert no force** in the layout, and a legend checkbox
hides them. A refuted relation must never spring its endpoints together and fake a connection the
graph already rejected.

**`GRAPH_REPORT.md`** carries the headline counts (straight from the engine, so they cannot drift),
per-community breakdowns across the three axes, the never-pruned falsification memory, the stale
verdicts (spans your source no longer contains), and per-source-file edge counts.

---

<a id="kg-eval"></a>
## `/burgess:kg-eval`

```
/burgess:kg-eval [graph.json]
```

**What it does.** Measures how good the extraction actually was, and how reliable the grounding
signal actually is. It runs two stages and appends the numbers to `.kg/PROGRESS.md` in your project.

**It measures; it never gates.** No metric here blocks the flow. In a development checkout, a stage
that falls short of its target auto-iterates — refine the pack and the extractor prompt, re-extract,
re-measure, up to three passes — then records the **best** result and proceeds. An installed plugin
never edits itself or rebuilds your graph: it records the refinements the numbers point to, each
checked against the current plugin first, because your graph keeps edges from every earlier build.

| Stage | Measures | Target |
| --- | --- | --- |
| **4** — extraction precision | An annotator labels a deterministic sample of edges against your source. Reports precision, astrology rate (fabricated + vague), span-support rate, and per-relation precision, then splits the sample by who wrote each edge (an extraction, a lead pass, an adversarial pass) and by the verdict grounding gave it. | precision `>= 0.70` |
| **7** — agreement + specificity | Two **independent** annotator passes over the same sample → Krippendorff's α. Then the specificity bridge-metric gate verdict. | α `>= 0.67` |

### Arguments

| Argument | Required | Accepted values | Default |
| --- | --- | --- | --- |
| `graph.json` | No | A path to a derived `graph.json` | the current derived graph |

### `graph.json` — what it does

| Form | Purpose |
| --- | --- |
| *(omitted)* | Grades the graph you have now: the engine's derived `graph.json`, re-projected for this project first. If the graph is empty, run `/burgess:kg-build` first. |
| A path | Grades a specific projection. Use it to compare a graph before and after a pack change, or to grade an archived build. |

### Examples

Grade the current graph:

```text
/burgess:kg-eval
```

Grade a specific projection — for instance, an archived build you want to compare against:

```text
/burgess:kg-eval snapshots/graph-before-pack-v2.json
```

### Reading the numbers

- **precision** = correct / labeled. The headline.
- **astrology rate** = (fabricated + vague) / labeled. Your grounding risk, measured rather than assumed.
- **span-support rate** = the fraction of claims with a real verbatim span. Reported alongside
  precision so that a high precision built on unverifiable spans is **visible**.
- **per-relation precision** shows which relations the extractor confuses — that is a pack problem,
  fixable in `pack/pack.yaml`.
- **Krippendorff's α ≥ 0.67** means the grounding signal is treated as reliable. Below that, it stays
  advisory.
- **specificity gate `on`** means specificity-weighted betweenness separates real bridges from vague
  high-traffic nodes, and may be promoted out of advisory. Otherwise degree remains the honest proxy.

Annotators can label a CSV but hold no graph-write tools: they **cannot** forge a verdict into the
canon. Precision is measured *about* the graph, never written *into* it.

Since 0.13.2 the annotators also start without your CLAUDE.md files and without Claude Code's memory index,
which a subagent gets by default. A note about an earlier eval could tell them how its coders labelled an edge.

---

<a id="kg-experiment"></a>
## `/burgess:kg-experiment`

```
/burgess:kg-experiment [--judge] [prompts_path]
```

**What it does.** Runs the one experiment that justifies the whole pipeline: a **blind** multi-arm
test over a fixed set of ideation prompts, in conditions that differ *only* in what context the
idea-generator is given. The generator never knows which arm it is in. Scoring is deterministic.

The headline question (0.12.0):

> Given the same source and the same budget, do the `graph` arm's ideas score higher **grounded novelty**
> than flat retrieval's (`rag`), prompt by prompt? Grounded novelty is how far an idea leaves the source's
> wording, times how much of its key-term weight the source still holds, so inventing things does not pay.

`control` is compared the same way in a second verdict. The method is pre-declared in
[`docs/fusion/EXPERIMENT.md`](fusion/EXPERIMENT.md).

The verdicts are appended to `.kg/PROGRESS.md` in your project and the command returns — **win or lose**. A
"did NOT clearly beat" or a "not measured" result is a legitimate, logged outcome: negative information about
the pipeline itself, not an error.

### Arguments

| Argument | Required | Accepted values | Default |
| --- | --- | --- | --- |
| `--judge` | No | The word `--judge`, anywhere in the line | Off: no judge runs |
| `prompts_path` | No | A path to a JSON array or newline-delimited file of prompts | 12 prompts drafted from your graph |

### `prompts_path` — what it does

| Form | Purpose |
| --- | --- |
| *(omitted)* | On the demo corpus, uses the 12 built-in ideation prompts. On any other source, drafts 12 from your graph's own concepts, in the corpus's language, and shows them before it goes on. |
| A path | Uses your own prompts — one per line, or a JSON array. |

Either way the prompts are saved as `.kg/experiment/prompts-<run>.json`; pass that file to repeat a run on
the same prompts.

### Examples

Run with the 12 default prompts:

```text
/burgess:kg-experiment
```

Run against your own prompt set:

```text
/burgess:kg-experiment experiments/my-prompts.txt
```

Same, from a JSON array:

```text
/burgess:kg-experiment experiments/prompts.json
```

Repeat a run on its saved prompts, with blind judges (about 0.8 million tokens more for 12 prompts):

```text
/burgess:kg-experiment --judge .kg/experiment/prompts-<run>.json
```

### The arms

| Arm | Context given to the generator |
| --- | --- |
| `control` | The prompt alone. No source, no graph. |
| `graph` | The prompt + a context pack drawn from the **grounded** graph. |
| `graph+generate` | The graph pack **plus** the hypothesized slate (one `kg_generate` call), clearly marked unverified. Tests whether *generating* lifts ideation beyond grounded context alone. |
| `graph+generate+dpp` | The same slate as `graph+generate`, in advisory-DPP order with its geometry labels. The candidate set is **identical** — this arm measures whether the *presentation* lifts ideation. |
| `rag` | The prompt + the source passages a naive flat retrieval finds (BM25 over the source's paragraphs, `harness rag-slices`), the same on every run of the same prompts. The honest strawman. |
| `lightrag` *(opt-in)* | The prompt answered by a real, published **GraphRAG** baseline (LightRAG) over the same corpus. A stronger strawman than flat `rag`. |

### The optional `lightrag` arm

Off by default, and entirely add-only: when it is not enabled, the experiment runs its other arms
unchanged and emits no error. To enable it, **all three** must hold:

1. Install the optional dependency: `pip install lightrag-hku` (or `pip install -e ".[lightrag]"`).
2. Opt in: `KG_LIGHTRAG=1`. (Optional tuning: `KG_LIGHTRAG_QUERY_MODE`, default `mix`.)
3. Provide `OPENAI_API_KEY` — LightRAG's default backend is OpenAI, so **this arm makes network and
   paid API calls.** That cost is the price of the stronger baseline, and it is why the arm is opt-in.

### Reading the scores

| Column | Meaning |
| --- | --- |
| `novelty` | `1 − trigram overlap with the source` — how far the ideas travel from the source's wording. |
| `support` | The share of a sentence's key-term weight (IDF over the source's paragraphs) held by terms the source contains, averaged. Terms are compared by stem, so a verb form the source does not use is not an invention; a term the source lacks weighs the most. |
| `grounded_novelty` | `novelty × support`, per idea. **The verdicts compare this one**, prompt by prompt. |
| `diversity` | Distinct trigrams / total trigrams pooled across the arm's outputs. Reported, not in a verdict. |
| `utility` | Density of English reasoning markers (`because`, `if`, `therefore`, `bridge`, `connect`). Reported, not in a verdict. |
| `unsupported_rate` | The share of judged sentences with support below 0.5. Reported, not in a verdict. |

An arm beats another when its grounded novelty is higher in enough prompts for a one-sided sign test at
5 %: 10 of 12. Ties within 0.005 count against it. Below five prompts, nothing can be decided.

The pairs:
- **graph vs rag:** the headline;
- **graph vs control;**
- **graph+generate vs graph:** does the hypothesized slate add to grounded context;
- **graph+generate+dpp vs graph+generate:** does the DPP presentation help;
- **graph vs lightrag:** when that arm ran.

The command surfaces these caveats when they apply:
- **No recorded failures.** If your graph has **zero** of them, the `graph` arm looks artificially clean.
  Run `/burgess:kg-ground` with the adversarial grounder before trusting a `graph`-wins verdict.
- **Support could not be checked, or failed its check.** `rag` writes from source passages and `control`
  from nothing, so `rag`'s support must exceed `control`'s by 0.10. When it does not, support measures
  nothing on your source, and every verdict reads "not measured".
- **Utility measures nothing.** Its markers are English words, so on a corpus in another language it is 0
  for every arm.

Through 0.11.x the headline asked whether `graph` beat `control` on novelty. Novelty is distance from a
source the control arm never sees, so on three field runs the graph arm could not have won it.

The subagent that writes the ideas has no shell (since 0.11.8). Only the command's own steps use one: the
environment check, the rag passages, the scoring and the log entry.

It answers every arm in one context, so its blindness is procedural. Since 0.13.1 it writes two drafts on the
way: the control answers before its first graph call, and the graph-based arms before it reads any rag
passage. `harness evaluator-order` checks two things: that the drafts came in that order, and that the final
file carries them unchanged. The log records the result as **Evaluator order**.

Since 0.13.2 the evaluator and the judges start without your CLAUDE.md files and without Claude Code's memory
index, which a subagent gets by default. A session that saves each run's results in its memory would otherwise
tell the next run's blind agents what the last one found.

### The blind judge (`--judge`, 0.13.0)

The lexical score cannot tell a good idea from a bad one, only how it uses the source's words. With `--judge`,
one fresh `kg-judge` subagent per prompt reads that prompt's ideas the way a careful reader would.

**What a judge sees.**
- Every arm's idea, plus two controls the command writes: a **decoy**, whose central support is invented, and
  a **positive control**, whose facts are real and come from at least two documents. The harness checks both
  before any judge runs.
- Each item labelled A, B, …, in a seeded order that rotates per prompt, with its own passages from the source.
  The labels' meaning stays out of the judges' reach.
- Nothing about the study. A judge's prompt does not say how the ideas were written or that controls exist
  (0.13.2; 0.13.0's said both).

**What a judge scores.**
- **grounded:** its claims hold in its evidence;
- **useful:** it is specific enough to test or apply.

It ranks the items, and never scores novelty. Evidence retrieved for an idea's own words cannot show that the
idea restates the source in other words, so a novelty score could reward an idea for its phrasing alone
([`EXPERIMENT.md`](fusion/EXPERIMENT.md), "novelty and paraphrase").

**Checks and verdicts.** Every run checks the judge itself:
- **V1:** the decoy must be the least grounded item;
- **V3:** the positive control must score 4 or more;
- V1 and V3 must each hold in 10 of 12 prompts;
- **V2:** the arms must out-score the decoys on grounded by 1.0.

If any check fails, the judge's verdicts read "not measured". Otherwise its graph vs rag verdict, decided on
the rankings by the same sign test, becomes the headline, and the lexical verdicts follow as a second reading.
The judge's score is saved as `.kg/experiment/judge_score-<run>.json`, and its packets and verdicts stay in
`.kg/experiment/judge-<run>/`.

**Cost.** Each judge reads a packet of about 35,000–40,000 tokens and ends with 60,000–80,000 tokens of context.
For 12 prompts that is about 0.8 million new tokens, plus about 1.3 million read back from the prompt cache,
measured on two field runs. That cost is why the judge is opt-in.

---

## Behind the commands

The nine slash commands are a thin language layer over **33 MCP tools** exposed by the `burgess`
server — the trust boundary where LLM work stops and the deterministic engine begins. Those tools
have **no slash**. Just ask for them in plain words:

```text
Is the Burgess engine running?          → kg_ping
What's in the graph right now?          → kg_status / kg_metrics
Show me the node called "compression"   → get_node
What should I work on next?             → kg_agenda
Rename this node                        → kg_rename
Merge these two nodes                   → kg_merge
```

The full tool surface, the write-boundary contract, and the divergence engine's internals are
documented in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## What none of these commands guarantee

In the spirit of the project, honestly:

- **Grounding guarantees fidelity to your source, never truth about the world.** A grounded claim
  means a verbatim span in *your* document supports it — not that the document is right.
- **Novelty numbers are variety proxies**, not novelty against prior art.
- **The cliché map hedges cliché; it does not guarantee freshness.**
- **The judge is bounded, not infallible.** Bad ideas can still reach you. That is by design: you are
  the selector.
- **The DPP presentation is advisory.** Whether it lifts downstream ideation was measured blind, and
  the shipped default follows that measurement rather than our enthusiasm.
