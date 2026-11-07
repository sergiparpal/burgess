## A Complete Walkthrough — from a blank page to grounded knowledge

New to Burgess? This guide walks you through one full creative cycle, start to finish, in plain
language. You don't need to be a programmer. If you can chat with Claude Code and edit a text file,
you can use every command here.

We'll follow a realistic project: you have a topic you want to think creatively about **and** a
document (a report, an article, your own notes) you want to turn into knowledge you can actually
trust and query. Burgess handles both halves of that job — and connects them.

> **The one idea that explains everything below:** the clever math in Burgess only ever finds ideas
> that are *new* or *different*. It never decides what is *true*. Only checking an idea against your
> own documents decides that. Keep that split in mind and the whole tool makes sense.

---

### Before you start (a five-minute setup)

**1. Install the plugin.** In Claude Code, run:

```text
/plugin marketplace add sergiparpal/Burgess
/plugin install burgess@sergiparpal
```

**2. Let it warm up once.** The first time it loads, Burgess quietly sets up a small local
workspace for itself and downloads a lightweight "similarity" model (about 120 MB, one time, cached
afterward). This all runs **on your own machine** — nothing about your ideas or documents is sent
anywhere for this part. Give it a minute the first time. If Claude Code says the `burgess` server
failed to connect, the setup simply hasn't finished yet: wait a minute or two, then reconnect it from
`/mcp` (or open a new session).

**3. Know where your work lives.** Everything Burgess creates is saved in a hidden folder called
`.kg/` inside whatever project folder you're working in. That folder *is* your knowledge — it's
plain files you can back up, put in Git, or even open and read. Two practical consequences:

- Work in the **same project folder** to keep adding to the **same knowledge graph**. A different
  folder means a fresh, separate graph.
- Your brainstorming sessions live in a separate spot (`.kg/diverge/`) from your grounded knowledge
  (`.kg/`), so the two never get confused.

**4. Have your source material ready.** To build a graph you'll want one or more documents in
`.md` (Markdown) or `.txt` (plain text) format. A single file, a whole folder of them, or a
pattern like `notes/*.md` all work.

---

### The mental model (worth two minutes)

Burgess builds a **knowledge graph**. That's just a fancy word for a web of notes:

- **Nodes** are the concepts — one idea per node. Under the hood each node is a single, human-
  readable Markdown file. You can open and edit them by hand if you ever want to.
- **Edges** are the relationships between concepts — "this *grounds* that", "this is *attacked by*
  that", "this *bridges* those two", and so on.

Every relationship carries a **status** that tells you how much to trust it. When you later look at
your graph (with `/kg-view`), you'll see these as colors and line styles:

| What you see | What it means |
|---|---|
| **Solid green line** | **Grounded** — a real, word-for-word sentence in your document backs this up. Trustworthy. |
| **Dashed line** | **Unverified** — extracted but not yet checked. A candidate, not a fact. |
| **Dotted line** | **Hypothesis** — a machine-proposed idea. Interesting, but no evidence yet. |
| **Red line** | **Failed / rejected** — this was checked and *didn't* hold up. Burgess keeps it on purpose, as a memory of what didn't work. |

That red-lines-are-kept detail matters: Burgess never quietly deletes its mistakes. Failures become
permanent memory, so the same dead end is never proposed to you twice.

There are two modes of work, and Burgess is built around the difference:

- **Diverge** — generate lots of *different* ideas without collapsing into the obvious. This is
  playful and wide.
- **Converge** — check ideas rigorously against evidence and keep only what holds. This is careful
  and narrow.

Throughout, **you are the selector.** Burgess proposes, measures, and organizes — but it's designed
so that *you* decide what to keep, and *your documents* decide what's supported.

---

### The full workflow, phase by phase

Here's the whole cycle. You won't always use every phase — skip freely — but this is the complete
map. In each phase you just type a slash command in Claude Code and follow along in chat.

```text
  BRAINSTORM        CAPTURE           BUILD            VERIFY           EXPAND           USE
 /kg-diverge  →  materialize pins  →  /kg-build   →  /kg-ground   →  /kg-generate  →  /kg-query
 (wide, free)     (keepers →           (document →     (check vs        (new ideas       /kg-view
                   graph as             graph)          source)          from the         (read &
                   hypotheses)                                           graph)            see it)
```

---

#### Phase 1 — Brainstorm without the clichés (`/kg-diverge`)

Start here when you have a *question or brief*, not yet a document. No graph is needed — this phase
is completely standalone.

Type a command with your brief:

```text
/kg-diverge names and angles for a calm, screen-free bedtime routine for toddlers
```

Burgess runs at **balanced** reach unless you say otherwise — novel ideas that still hold together.
Add `wild` on the end for further-out ideas, or `conservative` for safer, more buildable ones. Reach
changes only how *far* the ideas go, never how *varied* they are: every slate is still built from
genuinely different mechanisms. You can change it any round.

What happens next is a guided back-and-forth:

1. Claude first jots down the **most obvious, clichéd answers** to your brief — and then deliberately
   steers *away* from them. (Honesty note: "obvious" is Claude's guess at what's obvious. This
   hedges against clichés; it can't promise the world has never thought of your idea.)
2. Claude generates a batch of candidates, each built around a *different underlying mechanism* —
   not just different wording, but a genuinely different way the idea works.
3. Burgess's local engine measures how spread-out the batch is and picks a **diverse slate** to show
   you, with a one-line "why this one" for each.
4. You steer, in plain chat:
   - **Pin** the ideas you like ("pin the second and fourth"). Pins are your strongest signal —
     Burgess keeps exploring *from* them and never forgets them.
   - **Discard** ideas you want to stop seeing ("drop the first one"). Discards are remembered too,
     so that direction won't come back.
   - Answer the occasional quick **"A or B?"** question to sharpen the direction.
5. Loop as many rounds as you like. If the ideas start looking samey, Burgess notices and
   automatically pushes for more variety — you don't have to manage that.

When you're happy, you'll have a set of **pinned** ideas. Nothing has touched your knowledge graph
yet — pins just live in your brainstorming space.

> **Good to know:** the "novelty" numbers you'll see are a *variety* measure — how different an idea
> is from the *other ideas in this session* — not a claim about originality versus the real world.
> They help you see spread; they don't rank quality.

---

#### Phase 2 — Keep the good ones (materialize your pins)

When you want to carry your favorite pinned ideas into your actual knowledge graph, just say so in
chat — for example, *"let's move these pinned ideas into the graph."* This is a deliberate step:
**nothing enters your graph automatically.** Pinning keeps an idea; *materializing* is the separate,
explicit act of promoting it.

Each materialized idea enters as a **hypothesis** (a dotted-line, "no evidence yet" node), with a
note in its body recording that it came from this brainstorm. Two things to expect:

- If you don't have a source document/graph yet, that's fine — the ideas simply **wait** as
  hypotheses until you give them something to be checked against.
- Later, when you *check* a materialized idea against your sources, there are two outcomes. If it's
  simply **not supported yet** — a brand-new idea usually won't have a quote waiting in your existing
  sources — it just **stays in the graph as a hypothesis**, recoverable; add sources for the ideas you
  want to promote. Only if an idea is actively **disproven** does Burgess fold it back into that
  brainstorm's discards, so it won't be re-suggested. Your brainstorming and your fact-checking share
  one memory.

---

#### Phase 3 — Turn a document into a graph (`/kg-build`)

Now the convergence side. Burgess builds from the source you gave it at install, `source_path`: one
document, a **whole folder**, or a **pattern**. On its own, the command builds all of it:

```text
/kg-build
```

To build only part of it, name a file, folder or pattern **inside** that source:

```text
/kg-build research/chapter-1.md     (one document of a source folder)
/kg-build research/*.md             (a matching set of its files)
```

That source is also what every snippet is checked against, so a path outside it cannot work: every
relationship extracted from it would be rejected. To build from somewhere else, change `source_path`
(`claude plugin configure`, see the README's configuration reference) and restart Claude Code.

Burgess reads your document **section by section**, and for each section it pulls out the concepts
and the relationships between them, writing them into your graph. Every relationship it extracts is
tagged with the exact source file it came from and, crucially, a **word-for-word snippet** ("span")
from your text that it's based on. If a snippet doesn't actually appear in your document, Burgess
rejects it — this is the anti-fabrication guarantee. At this stage everything is written as
**unverified** (dashed lines): extracted, but not yet checked.

**You can build incrementally.** The graph is additive: run `/kg-build` again later and it *adds* to the
same graph rather than wiping it. Shared concepts across documents naturally merge into one node. The easy
way to grow it is to make `source_path` a **folder**: drop a new document into it (Burgess notices new
files without a restart) and build just that one with `/kg-build <folder>/<new-document>.md`. So a
perfectly normal pattern is: build one document, then another, then another, growing one graph over time.

---

#### Phase 4 — Fact-check against your source (`/kg-ground`)

This is the heart of the "converge" side, and the **only** command that can mark something as
trustworthy:

```text
/kg-ground
```

Burgess goes through the unverified relationships and, for each one, tries to confirm it against your
actual source:

- If a real, supporting sentence backs it up, the relationship is **promoted to grounded** (solid
  green). It has earned trust.
- If it can't be supported, it's **rejected**, and if it was genuinely tested and failed, that
  failure is **remembered forever** (red line, never deleted). That memory then stops the same weak
  idea from being proposed again down the road.
- Vague, over-connected "hub" concepts get deliberately challenged, so a fuzzy idea can't look
  important just by touching everything.

You can also focus it on one area — `/kg-ground betweenness` — instead of the whole backlog.

> **The honest limit, stated plainly:** *grounded* means "a sentence in **your** document supports
> this." It does **not** mean the claim is true about the world. Burgess guarantees faithfulness to
> your source, not correctness of your source. If your document is wrong, a grounded edge just
> faithfully reflects that.

---

#### Phase 5 — Let the graph suggest new ideas (`/kg-generate`)

Once you have a grounded graph, it can become a source of *fresh* ideas — not from a blank page, but
from the structure of what you already know:

```text
/kg-generate
```

Burgess looks at the shape of your graph and proposes new candidate connections using several
different strategies — for example, spotting two well-grounded ideas that have never been linked,
or surfacing neglected concepts sitting out on the edges. Each proposal is phrased as a single,
checkable sentence and added to your graph as a **hypothesis** (dotted line, no evidence yet).

The philosophy here is deliberate: **generate freely, judge afterward.** Nothing is filtered out for
being "low quality" at this stage — everything is offered. To find out which proposals actually hold
up, you simply run `/kg-ground` again over the new hypotheses. Grounding is always the filter, and it
always comes last.

---

#### Phase 6 — Challenge your blind spots (`/kg-perturb`) *(optional)*

Every idea in Phase 5 comes from *your* graph's own way of seeing things — so it can only ever find
what your current view already implies. `/kg-perturb` is the one command that pushes against that.
You give it a **second document** (a different source, or the same territory seen a different way):

```text
/kg-perturb path/to/a-different-source.md
```

Burgess builds a second, independent picture of the topic and looks for connections that exist in
*that* picture but are missing from yours — precisely the bridges your own perspective would resist.
It's honest about the catch: a second viewpoint doesn't remove blind spots, it *swaps* them for
different ones. The connections that survive **both** views are the ones worth grounding.

---

#### Phase 7 — Ask your graph questions (`/kg-query`)

Now put the graph to work. Ask a question in plain language:

```text
/kg-query what defeats the generality confound, and how well-supported is that?
```

Burgess answers **from your grounded graph, not from its own general knowledge** — and it's scrupulous
about labeling how trustworthy each part of the answer is. Grounded facts are presented as facts;
unverified guesses and machine hypotheses are shown separately and clearly flagged as *not yet
confirmed*. It will also tell you what it *doesn't* have, rather than making something up. If there's
relevant "here's what failed before" memory, it surfaces that too.

---

#### Phase 8 — See your graph (`/kg-view`)

To actually look at what you've built:

```text
/kg-view
```

This produces two things you can open right away, both fully offline:

- **`graph.html`** — an interactive map of your whole graph. Open it in any web browser (no internet
  needed). This is where the color code from the mental model above comes to life: green solid edges
  are grounded, red are failed-and-remembered, dashed are unverified, dotted are hypotheses. Bigger
  nodes are more connected; a gold ring marks a genuine "bridge" concept.
- **`GRAPH_REPORT.md`** — a written summary: how many concepts and relationships you have, the
  breakdown by trust level, the list of remembered failures, and a per-document tally if you built
  from several sources.

`/kg-view` is strictly a window — it never changes anything. To change the graph, you go back through
build and ground.

---

#### Phase 9 — Measure and prove it (`/kg-eval`, `/kg-experiment`) *(advanced, optional)*

If you want hard numbers rather than a vibe, Burgess ships its own honesty checks:

- **`/kg-eval`** measures how *precise* the extraction was (does each relationship really have
  support?) and how *reliable* the grounding is (would two independent passes agree?). It reports the
  numbers and, if a stage falls short, quietly tries to improve and re-measures.
- **`/kg-experiment`** runs a genuine blind test of the whole premise: does having the graph actually
  help you generate better, more varied ideas than just having the raw document — *without* inventing
  more unsupported claims? It compares several conditions fairly and records the verdict. This is how
  Burgess keeps itself honest instead of just asserting it works.

Most people never need these two. They're here because the project would rather be measured than
believed.

---

### Command cheat-sheet

| Command | When you reach for it |
|---|---|
| `/kg-diverge <brief> [domain-template] [reach]` | Brainstorm wide, fight clichés, pin the keepers. No graph needed. Add `wild` or `conservative` to change how far out it goes (default `balanced`), and name a domain template (e.g. `marketing`) to pick the axes it spreads across. |
| *materialize* (just ask) | Promote your pinned ideas into the graph as hypotheses. |
| `/kg-build <file/folder>` | Turn a document (or many) into a graph. Adds to what's there. |
| `/kg-ground` | Fact-check against your source. The **only** way to mark something trusted. |
| `/kg-generate` | Let the graph's structure suggest new candidate ideas. |
| `/kg-perturb [2nd source]` | Bring in an outside viewpoint to expose blind spots. Give it another document, or a prior construction's `graph.json`. |
| `/kg-query <question>` | Ask your graph, with trust levels attached to every answer. |
| `/kg-view` | Render an offline interactive map + a written report. |
| `/kg-eval` | Measure extraction precision and grounding reliability. |
| `/kg-experiment` | Blind-test whether the graph really improves ideation. |

Most commands take optional arguments this table leaves out — every one of them, with worked examples,
is in the [command manual](docs/COMMANDS.md).

---

### A few things that will save you confusion

- **Diverging and grounding are different jobs.** One generates; the other verifies. Don't expect the
  brainstormer to fact-check, or the fact-checker to be imaginative. Used together, in order, they're
  the whole point.
- **Green means "your document says so," not "this is true."** The strongest, most useful, most
  honest promise Burgess makes — and its clearest limit.
- **Nothing important happens behind your back.** Ideas don't enter your graph until you materialize
  them; nothing is marked trusted until you ground it; the viewer never edits anything.
- **You can edit by hand.** Every concept is a plain Markdown file. If you want to fix a label or a
  description yourself, you can — the graph is yours, not a black box.
- **Failures are features.** Red lines aren't clutter to clean up; they're memory. They're what stops
  Burgess from walking you into the same dead end twice.
- **Bad ideas can still reach you — on purpose.** The diversity engine can nudge, but it can't veto.
  It's designed to hand you the unusual and let *you* be the judge, rather than quietly filtering to
  a safe, average slate.

That's the full cycle: brainstorm freely, keep what you like, build knowledge from your sources,
verify it honestly, let it suggest more, and query what you've earned — with a clear-eyed line between
what's imagined and what's grounded at every step.
