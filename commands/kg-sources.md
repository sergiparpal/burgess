---
description: Register external sources (a URL or a local file) with an epistemic level, so grounders can support or refute graph items with verbatim spans from them; find candidate sources for the items waiting for one; give your notes a level too; set the level a project requires to verify, or build a graph from registered sources alone; list what the grounded claims rest on.
argument-hint: "[add <url-or-path> | find [focus] [n] | list | set <name> key=value ... | policy [key=value ...]]"
allowed-tools: Task, mcp__plugin_burgess_burgess__kg_source_add, mcp__plugin_burgess_burgess__kg_source_find, mcp__plugin_burgess_burgess__kg_source_list, mcp__plugin_burgess_burgess__kg_source_set, mcp__plugin_burgess_burgess__kg_source_policy
---

# /burgess:kg-sources — sources with an epistemic level (0.21.0, 0.22.0, 0.24.0)

Every verdict so far was judged against the configured sources: the user's own notes. So `grounded` means
"my notes say it". This command brings in **outside evidence**: a page or a file the engine copies into the
project's `evidence/` directory, with a level. A grounder can then cite a verbatim span from that copy, to
support an unverified item (the pins waiting for new sources come back to the queue on their own when the copy
is usable under the project's policy) or, through the adversarial grounder, to refute one.

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

**This command needs no shell, no file access and no web tool of its own.** Do not run Bash, do not `Read`
files, and **never use WebFetch or WebSearch yourself**: WebFetch returns a small model's answer about a page, not
the page, so a "verbatim" span from it would be verbatim of a paraphrase. The engine fetches and copies the page
itself (`kg_source_add`). The user names a source (`add`), or `find` (0.24.0) suggests candidates: its
`kg-scout` subagents search and read pages through the engine, and the user picks what to register.

**Arguments, as typed:** `$ARGUMENTS`

Split it at the first space. The first word is the action, and the rest of the line is its argument:
- `add` — the rest of the line is ONE URL or ONE path, taken whole (a path may contain spaces; drop surrounding
  quotes if the user typed them).
- `find` — the rest of the line is optional: focus words (only the waiting items whose text or id holds every one
  of these words: what the idea says, not only its title, accents ignored) and, as its last word, a number (how
  many items to look for this run, 1-20; default 6).
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
     `/burgess:kg-sources add <that path>`. `fetch-blocked` (0.23.1): the site sent the engine a bot check
     instead of the page (`detail` says how the engine knows); tell the user to open the page in their browser,
     save it as an `.html` file (Ctrl+S, HTML only) and run `/burgess:kg-sources add <that path>`. Some sites
     answer the engine on one machine and challenge it on another. `pdf-not-supported`: convert the PDF to
     Markdown and add that file.
2. From the preview (`title`, `authors`, `meta`: `citation_journal_title`, `citation_doi`, `og:site_name`, … ,
   `published`, the address and the `excerpt`), **propose** a level, a role and any marks, each with a
   one-line reason. Propose level 1 only when the preview shows peer review (a journal or conference in the
   metadata, a DOI of a reviewed venue); a preprint server is level 4. Mark `interest` when the author speaks
   about its own product, method or result. When unsure between two levels, propose the lower one and say so.
   Name the authors as the preview's `authors` gives them (0.25.1), or as the excerpt prints them; with neither,
   name none. Never from memory or from earlier notes: a name a session wrote down can be wrong.
3. Show the proposal and **stop: ask the user to confirm or correct it.** Do not register before the user
   answers.
4. On the user's answer, call `kg_source_add` again with the same `url`/`path` and the confirmed `level`,
   `role`, `marks`, plus `published` when the user gave a date (otherwise the engine keeps the date the page
   declares) and a `note` saying why this level. When the user registers it against an idea (a candidate with the stance
   `refutes`, or one they say goes against an idea), pass `against_items=<those ids>` (0.25.0). Pass `build=true` only when the user asked to build the graph
   from this source (when the project builds from registered sources, `build_from_notes` false, ask). Under
   `find`, pass `for_items=<the item ids it was found for>`.
   - `already-registered`: the same text is already a source (`name`). Report it and stop.
   - `same_url_as` in the result: the URL had been registered before with other text. Tell the user, and ask
     whether the old copy should be marked `superseded` (`set <old name> marks=superseded`).
5. Report in a few lines: the registered `name`, its level, role and marks, and what happens next. When the
   result's `source.usable` is true, the waiting items in its `comes_back` (0.24.5) come back to the next
   `/burgess:kg-ground`, which judges them against it; the other waiting items (`still_waiting`) keep waiting.
   Name each item with the reason its `why` gives, never another:
   - `found_for`: the source was found for it;
   - `words`: a paragraph of the source shares three of its words, the ones in `words`;
   - `no-words`: it has no words to test, so any new usable source brings it back.
   An empty `comes_back` means no waiting item comes back. When the result has `to_attack` (0.25.0), the source was
   found AGAINST those items (a scout proposed it with the stance `refutes`, or you named them in `against_items`):
   they do not come back to be grounded on it; the next `/burgess:kg-ground` has the adversarial grounder attack
   them, and a refutation it finds is confirmed by a second grounder before the idea is marked refuted. Name them
   apart. When `source.usable` is false, they all keep waiting
   and the source changes nothing until the policy accepts its level. Nothing was added to the graph. (Through
   0.24.4 the report had only `found_for`, and an item found for the source was reported as coming back for
   sharing words with it; through 0.23.1 every waiting item came back.)

## find

Suggests outside sources for the items waiting for one (0.24.0): the claims a `/burgess:kg-ground` grounder judged
and left unverified because no usable source supports them. It proposes; the user picks; each pick goes through
`add` like any source. Nothing is registered or judged here.

1. Call `mcp__plugin_burgess_burgess__kg_source_find` with `focus` (the focus words) and `limit` (the number, or
   nothing for the default). Report in a line `waiting_total`, `never_searched`, how many items this run looks
   for, and `openalex_searches_today`. With no `items`, say the result's `note` and stop.
2. Launch `burgess:kg-scout` subagents with the Task tool, **in one message** so they run in parallel, three items
   per scout. Give each scout its items as JSON exactly as `kg_source_find` returned them, and `required_level`.
   Tell it nothing else about the project: not its folder, not its name. Wait for every scout.
3. Show the candidates, numbered across the whole run, item by item:
   - the item: its id and the first line of its `text`;
   - each candidate: its number, title, its authors when the scout's candidate carries them (`authors`, which
     the scout copies from the engine; with none, name no author), venue and year, the proposed level and role
     with the reason, the stance
     (supports, refutes, related), the verbatim passage (shortened only with "…"), the address, and "the engine
     cannot read this page: save it from your browser" when `readable` is false;
   - the queries the scout ran, for and against, and its note when it found nothing. Each item is owed three
     searches: the catalogue for and against, and the web for (0.24.2). When a scout's queries lack one, say so
     for that item: nothing was looked for that could refute it, or the web was not searched.
   Then the totals: items searched, candidates, searches. Say once that a level is a proposal from the catalogue's
   facts and the page's metadata, and a stance is the scout's reading of one passage, never a verdict:
   `/burgess:kg-ground` judges after a source is registered.
4. **Stop and ask which numbers to register**, with the exact reply to type, for example «Registra 1 y 4».
   Several at once is fine. Register nothing before the user answers.
5. For the numbers the user picks, run `add` with each candidate's address: the previews, then the proposals
   together (start from the scout's level, role and reason, corrected by what each preview shows), then one
   confirmation for all of them, with the exact reply to type («Confirmo todas», or the corrections). Then call
   `kg_source_add` for each with `for_items=<its item id>`. For a candidate the engine cannot read, give the
   command to run once the user has saved the page: `/burgess:kg-sources add <path of the saved .html>`. The
   engine matches it to its item by DOI or title.
6. When something was registered, say which items wake for the next `/burgess:kg-ground` (each result's
   `found_for`, and any waiting item whose words the source contains) and that the other waiting items keep
   waiting.

What leaves the machine is the scouts' queries: topic words, sent to OpenAlex through the engine and to the web
search, never the user's name, paths or project. Without a key OpenAlex lets one network run about 100 searches a
day; a scout that meets `search-budget` keeps to the web for the rest of the run. The engine runs one catalogue
search at a time and retries once when OpenAlex asks it to slow down; a search still refused that way is
`search-rate-limited`, with budget left (0.24.3). Say the daily budget ran out only when a scout met
`search-budget`, and report `openalex_budget_left_usd` when `kg_source_find` gives it.

## list

Call `mcp__plugin_burgess_burgess__kg_source_list` and report:
- each source: name, title, level (and its name), role, marks, usable or not (and why), published date, and
  the address or "local file";
- `problems` (an edited copy is left out: the engine never vouches for a copy it did not write; the user
  registers the source again) and `unregistered` files, if any;
- `notes`: each of the user's notes with its level (and whether the user set it or it is the default), and
  whether it is usable and built into the graph; and the `policy`, with `usable_sources` (how many files may
  support anything) and its `warning` when there is none.
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
`notes_level`, `build_from_notes`, `notes_path`), or with none to read it. Report the policy, the notes with their levels, and
`on_unusable_total`: the grounded claims that no longer rest on a usable source (they keep their verdict). **When
the result carries `warning`** (`usable_sources` is 0), say it first and plainly: under this policy no source can
support or refute anything, so nothing can be verified until a source at the required level is registered or
the level is lowered, and `/burgess:kg-ground` leaves the items that need support out until then. Two common
uses:
- **Rely only on reviewed sources:** `policy required=1`. The notes still propose claims, and
  `/burgess:kg-ground` verifies each one only on a passage from a level-1 source, or leaves it unverified
  until one is registered.
- **Build a graph from level-1 sources alone:** `policy required=1 build_from_notes=no`, register each paper
  with `build` (`add <url or path>`, then confirm `build`), and run `/burgess:kg-build`.
- **Give this project its own notes** (0.23.0): `policy notes_path=<a folder, file or glob inside the project>`,
  `notes_path=none` for no notes, or `notes_path=default` to go back to the plugin's `source_path`. The plugin's
  option is one value for every project (Claude Code keeps plugin options per user), so this is how two
  projects read different notes. A path outside the project is refused: a cloned repository must not choose
  files outside itself. Report `policy.notes_from` (`project`, `none` or `global`) and `policy.notes_folder`.
  The notes are what a build extracts and what claims are verified against, so a change takes effect at once:
  the next `/burgess:kg-build` reads the new notes, and verdicts already given keep their state.
A looser policy brings back the items waiting for new sources only when it makes usable a source they were not
judged against and that bears on them (their words, or a `find` for them); a stricter one leaves them waiting.
Never tell the user that a policy change brings them back otherwise.

## Rules

- Never invent a source, a title, an author, a date or a level the preview does not support. Never register a
  source the user did not name or pick from `find`.
- Never paraphrase a source into the evidence directory, and never write files: only `kg_source_add` writes a
  copy.
- The level is a property of the source, not of a claim, and never a verdict. Never say a claim "is true"
  because its source has a high level.
- Never change the policy or a note's level on your own initiative: the user decides what the project
  requires.
