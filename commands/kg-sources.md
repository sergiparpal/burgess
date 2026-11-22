---
description: Register external sources (a URL or a local file) with an epistemic level, so grounders can support or refute graph items with verbatim spans from them; give your notes a level too; set the level a project requires to verify, or build a graph from registered sources alone; list what the grounded claims rest on.
argument-hint: "[add <url-or-path> | list | set <name> key=value ... | policy [key=value ...]]"
allowed-tools: mcp__plugin_burgess_burgess__kg_source_add, mcp__plugin_burgess_burgess__kg_source_list, mcp__plugin_burgess_burgess__kg_source_set, mcp__plugin_burgess_burgess__kg_source_policy
---

# /burgess:kg-sources — sources with an epistemic level (0.21.0, 0.22.0)

Every verdict so far was judged against the configured sources: the user's own notes. So `grounded` means
"my notes say it". This command brings in **outside evidence**: a page or a file the engine copies into the
project's `evidence/` directory, with a level. A grounder can then cite a verbatim span from that copy, to
support an unverified item (the pins waiting for new sources come back to the queue on their own) or, through
the adversarial grounder, to refute one.

**The level measures the filter a text passed before it was published, never whether a claim is true.** The
grounder still judges only whether a passage says what a claim says. The level decides what may be used:

| Level | Filter | Examples |
|---|---|---|
| 1 reviewed | peer review | systematic reviews and meta-analyses, journal or conference papers with review |
| 2 institutional | a body answers for it, with a published method | official statistics, reports of public bodies, standards (RFC, ISO, W3C), official documentation of a language, protocol or product, university textbooks |
| 3 editorial | an editor checks and corrects | press with corrections, news agencies, edited popular science, fact-checkers, technical books |
| 4 author or community | the author's reputation, or moderation after publication | preprints, code, changelogs, postmortems, specialist and engineering blogs, talks, Wikipedia, Stack Overflow, forums |
| 5 unfiltered | none, or made to sell, persuade or rank | social posts without sources, promotional content, SEO or generated-text farms, pseudoscience, texts with no author or date |

- **Role**: `primary` (the origin of the fact: the data, the experiment, the spec, the code, the author's own
  statement), `secondary` (analyses primaries and cites them), `tertiary` (summarizes without pointing to the
  origin; good for finding the primary, not as final support).
- **Marks**: `interest` (the author gains if the claim holds: a vendor about its product), `corrected`,
  `retracted`, `superseded` (a newer version of this same document exists).
- **A source accredits what it was in a position to know.** A level-5 source is an object of study only: it
  supports and refutes nothing. A retracted or superseded source supports and refutes nothing either.
- **The user's notes have a level too** (0.22.0): 4 by default, a text by an author nobody reviewed, unless the
  user sets another per file. The same rules hold for every source: a lower level never fails a higher one, so
  a reviewed paper can fail a claim only the notes support, and a clash the level does not settle stays a
  visible dispute.
- **The project decides the level it requires** (`policy`): the worst level that may still support or refute.
  4 (the default) accepts everything but unfiltered sources. 1 accepts only peer-reviewed ones: the notes then
  propose claims, and a claim is verified only on a reviewed source's passage.

A registered source is **evidence, not content**: `/burgess:kg-build` does not extract it, unless the user
registers it with `build` (0.22.0), which is how a graph is built from level-1 sources alone (see `policy`).

**This command needs no shell, no file access and no web tool.** Do not run Bash, do not `Read` files, and
**never use WebFetch or WebSearch for this**: WebFetch returns a small model's answer about a page, not the page,
so a "verbatim" span from it would be verbatim of a paraphrase. The engine fetches and copies the page itself
(`kg_source_add`). This version does not search for sources: the user names them.

**Arguments, as typed:** `$ARGUMENTS`

Split it at the first space. The first word is the action, and the rest of the line is its argument:
- `add` — the rest of the line is ONE URL or ONE path, taken whole (a path may contain spaces; drop surrounding
  quotes if the user typed them).
- `list`, or nothing at all — list the registered sources.
- `set` — the next word is a registered source's name (`ext-….md`) or one of the user's notes (its file
  name), then `key=value` pairs: `level`, `role`, `marks` (comma-separated, or empty to clear them), `note`, and
  for a registered source also `published`, `derives_from`, `title`, `build` (yes/no). A value with spaces is
  wrapped in double quotes.
- `policy` — the rest of the line is `key=value` pairs, or nothing to show the policy: `required` (1-4: the
  worst level that may still support or refute), `notes` (1-5: the level of a note with no level of its own),
  `build_from_notes` (yes/no: whether the notes are extracted into the graph).
- Anything else: say which actions exist and stop.

## add

1. Call `mcp__plugin_burgess_burgess__kg_source_add` with `url=` (when it starts with http:// or https://) or
   `path=` (anything else; relative to the project), and `preview=true`. Nothing is written yet.
   - On an error, report it in one line and what to do. `fetch-failed` or `no-text`: the site refused the
     engine or the page needs JavaScript; the user can save the page's text as a `.md` file and run
     `/burgess:kg-sources add <that path>`. `pdf-not-supported`: convert the PDF to Markdown and add that file.
2. From the preview (`title`, `meta`: `citation_journal_title`, `citation_doi`, `og:site_name`, … ,
   `published`, the address and the `excerpt`), **propose** a level, a role and any marks, each with a
   one-line reason. Propose level 1 only when the preview shows peer review (a journal or conference in the
   metadata, a DOI of a reviewed venue); a preprint server is level 4. Mark `interest` when the author speaks
   about its own product, method or result. When unsure between two levels, propose the lower one and say so.
3. Show the proposal and **stop: ask the user to confirm or correct it.** Do not register before the user
   answers.
4. On the user's answer, call `kg_source_add` again with the same `url`/`path` and the confirmed `level`,
   `role`, `marks`, plus `published` when the user gave a date (otherwise the engine keeps the date the page
   declares) and a `note` saying why this level. Pass `build=true` only when the user asked to build the graph
   from this source (when the project builds from registered sources, `build_from_notes` false, ask).
   - `already-registered`: the same text is already a source (`name`). Report it and stop.
   - `same_url_as` in the result: the URL had been registered before with other text. Tell the user, and ask
     whether the old copy should be marked `superseded` (`set <old name> marks=superseded`).
5. Report in a few lines: the registered `name`, its level, role and marks, and what happens next: the pins
   waiting for new sources come back to the next `/burgess:kg-ground`, which judges them against this source
   too. Nothing was added to the graph.

## list

Call `mcp__plugin_burgess_burgess__kg_source_list` and report:
- each source: name, title, level (and its name), role, marks, usable or not (and why), published date, and
  the address or "local file";
- `problems` (an edited copy is left out: the engine never vouches for a copy it did not write; the user
  registers the source again) and `unregistered` files, if any;
- `notes`: each of the user's notes with its level (and whether the user set it or it is the default), and
  whether it is usable and built into the graph; and the `policy`.
- `support`: how many grounded edges and nodes rest on the user's notes (`own`) and on external sources, each by
  level, and on unchecked citations (support given as a citation the engine cannot check: registering that
  source and citing its span makes it checkable). Name the claims in `on_unusable` (whose support is no longer
  usable: a source since marked retracted, or below a required level raised since), if any: they keep their
  verdict, and the user may want them judged again.

## set

Call `mcp__plugin_burgess_burgess__kg_source_set` with the name and only the fields the user gave. Report the
`changed` fields and the source's new record. A change bears on verdicts given from now on; verdicts already
given keep their state (`list` names those now resting on an unusable source). For a note, propose a level from
what the user says the note is (a synthesis of reviewed papers they cite is still level 4: nobody reviewed the
synthesis; the papers themselves can be registered).

## policy

Call `mcp__plugin_burgess_burgess__kg_source_policy` with only the fields the user gave (`required_level`,
`notes_level`, `build_from_notes`), or with none to read it. Report the policy, the notes with their levels, and
`on_unusable_total`: the grounded claims that no longer rest on a usable source (they keep their verdict). Two
common uses:
- **Rely only on reviewed sources:** `policy required=1`. The notes still propose claims, and
  `/burgess:kg-ground` verifies each one only on a passage from a level-1 source, or leaves it unverified
  until one is registered.
- **Build a graph from level-1 sources alone:** `policy required=1 build_from_notes=no`, register each paper
  with `build` (`add <url or path>`, then confirm `build`), and run `/burgess:kg-build`.
A change of policy brings back the items that were waiting for new sources.

## Rules

- Never invent a source, a title, a date or a level the preview does not support. Never register a source the
  user did not name.
- Never paraphrase a source into the evidence directory, and never write files: only `kg_source_add` writes a
  copy.
- The level is a property of the source, not of a claim, and never a verdict. Never say a claim "is true"
  because its source has a high level.
- Never change the policy or a note's level on your own initiative: the user decides what the project
  requires.
