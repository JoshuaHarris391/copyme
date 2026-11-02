# Spec 02 — Style/content separation and exports

| | |
|---|---|
| Status | Blocked on spec 01 |
| Depends on | [Spec 01](01-exemplars-and-rules.md) — needs `Profile`, exemplars and rules |
| Gate | The exported card validates against the published Character Card V2 schema |
| Decisions assumed | [ADR 0003](../adr/0003-separate-style-from-content.md), [ADR 0004](../adr/0004-profile-json-is-the-contract.md), [ADR 0005](../adr/0005-no-prefill-in-exports.md) |

## Why

Two problems, both about what leaks out of a profile.

**Topic leaks into style.** The current vocabulary block lists the author's most
frequent words and phrases. On any real sample that list is mostly the sample's
subject, so the model writes about that subject. A profile of someone's work email
produces a model that keeps mentioning the quarterly report.

**The profile only reaches one place.** A pre-prompt pasted as a first message is one
of five places a voice is needed. Until the profile renders to a system prompt, a
character card and a machine-readable object, every other application has to
re-implement copyme.

After this milestone a profile goes into Maya, SillyTavern, Claude Projects or any
system-prompt field, and carries manner without carrying subject.

## Scope

1. Filter the vocabulary and phrase lists to style rather than content.
2. Mask one-off named entities in exemplars.
3. Render `Profile` to five export targets, plus the two partial formats Maya needs.
4. Report both a GPT-family and a Claude token estimate, labelled.
5. Add a provenance footer to every export.
6. Streamlit: an exports selector.

## Out of scope

- `score()` and the copying check that enforces the no-reproduction instruction —
  spec 03. Until then the instruction is unenforced, which is stated in the UI.
- The live contrastive tier — spec 04.
- Writing the PNG card file; `copyme card` arrives with the CLI in spec 03. This
  milestone produces the Character Card V2 **JSON**.

## Design

### Three filters, all on the existing parse

**Keep function and manner words; drop content words.** From the frequency ranking,
keep tokens whose POS is a conjunction, adposition, determiner, pronoun, particle,
adverb or interjection, plus a short allow-list of intensifiers and hedges. Drop nouns,
proper nouns and most verbs.

What survives is the author's connectives and qualifiers, which is what stylometry has
always found diagnostic.

**Keep idioms; drop topical phrases.** A repeated 2-to-4-word phrase survives only if
it contains no noun that is also in the sample's top-50 content nouns, and no named
entity. "The thing is", "I mean", "which is to say" survive. "The quarterly report"
does not.

**Mask names everywhere.** Named entities in exemplars are replaced with role
placeholders — `[a colleague]`, `[a city]` — when the entity appears **fewer than three
times** in the sample, so a one-off name cannot leak. Recurring names are kept: they
are the author's recurring world, and the research found masking names costs nothing
for style learning while the writer's recurring references are part of the voice.

Masking is controlled by `mask_names=True` and applies to the rendered exemplars, not
to the stored offsets, so turning it off never requires a re-parse.

### The instruction block states the separation

The instruction block gains a sentence that is load-bearing, not decorative:

> The examples show *how* this person writes, not what they know or believe. Do not
> import their subjects, names, settings or opinions.

That sentence is also what makes a profile usable as a character voice in an assistant,
where the character's circumstances must not come along.

### Five export targets

One `Profile` renders to all of them. Section order inside the prompt formats is fixed
(instruction, rules, exemplars, known failures, voice card) so API consumers can cache
the stable part.

| Target | Shape | Use |
|---|---|---|
| `first_message` | Markdown block, as today | Pasting into a ChatGPT, Claude or Gemini chat |
| `system_prompt` | The same without the "you are about to" framing, written as standing instructions | Claude Projects, custom GPTs, any application with a system field |
| `voice_card` | Five lines: the top rules plus "match frequency, not presence" | Re-pasting mid-conversation; a per-turn reminder |
| `sillytavern_card` | Character Card V2 JSON | SillyTavern or any front end reading the V2 spec |
| `json` | The full `Profile`: features, rules with bands, exemplars with reasons, known failures, provenance | Programs, including `score` and Maya |

Plus two partial formats for applications that assemble their own prompt:
`exemplars` (the exemplar block alone) and `rules` (the rules block alone). Maya uses
both — see [../product/integrations.md](../product/integrations.md).

**Character Card V2 mapping:** `description` from the rules, `mes_example` from the
exemplars in `<START>` dialogue format, `system_prompt` from the instruction block, and
`creator_notes` carrying the voice card with a note to paste it into the Author's Note
field at depth 4, which is SillyTavern's own anti-drift mechanism.

**No prefill is emitted.** Older SillyTavern presets lean on assistant-message prefill
to lock register; Claude Sonnet 4.6 and later reject prefill with a 400 error. The
in-voice opening line goes inside the system text instead.

### Token counting

`count_tokens` currently uses `cl100k_base`, and the README is candid that this is a
GPT-family count. Claude Sonnet 5 uses a new tokeniser producing roughly **30% more
tokens** for the same text than its predecessor, so a single number misleads.

The size indicator reports **two labelled estimates**: a GPT-family figure, and a
Claude figure computed as the GPT figure times 1.3 until an offline Claude tokeniser is
available. Both are labelled as estimates where they are estimates; the existing exact
or estimated distinction is kept.

### Provenance footer

Every export carries a footer naming:

- the copyme version
- the profile hash
- the sample's word count
- the model the live contrastive tier ran against, if any (empty until spec 04)

This is what lets a user tell two profiles apart six months later, and it is the
mechanism behind the "no feature strips attribution" commitment in
[../product/non-goals.md](../product/non-goals.md).

## Public API

```python
build_pre_prompt(
    profile: Profile,
    size: str = "standard",      # "compact" | "standard" | "full"
    format: str = "first_message",
    # "first_message" | "system_prompt" | "voice_card"
    # | "sillytavern_card" | "json" | "exemplars" | "rules"
) -> str

build_profile(
    analyser,
    ...,
    mask_names: bool = True,
)
```

`build_pre_prompt(results_dict)` with the v1 dict keeps working and keeps producing
the v1 block, so existing callers are unaffected.

## Acceptance criteria

Separation

- [ ] No noun, proper noun or non-allow-listed verb appears in the style vocabulary
      list for any golden sample.
- [ ] A phrase containing a top-50 content noun or a named entity is excluded from the
      idiom list.
- [ ] An entity appearing twice in the sample is masked in every exemplar; one
      appearing three times is not.
- [ ] A role placeholder is used, not a generic token: `[a colleague]`, never `[NAME]`.
- [ ] With `mask_names=False`, exemplar text is byte-identical to the source passage.

Exports

- [ ] The `sillytavern_card` output validates against the published Character Card V2
      schema.
- [ ] `json` round-trips: `Profile` → JSON → `Profile` compares equal.
- [ ] No export contains the string `prefill`, and no export emits an assistant-role
      message.
- [ ] `system_prompt` contains no second-person framing of the form "you are about to
      be given".
- [ ] `voice_card` is five lines or fewer and ends with the frequency reminder.
- [ ] Every export ends with the provenance footer, and the footer names no path, host
      or key.
- [ ] Section order is identical across `first_message` and `system_prompt`.

Token counting

- [ ] The size indicator shows two figures, each labelled with its model family.
- [ ] The Claude figure is 1.3 times the GPT figure, and the multiplier is named in
      the UI caption rather than hidden in code.

## Verification

```bash
poetry run python3 -m pytest tests/test_exports.py tests/test_separation.py -q
poetry run python3 -m pytest -q
```

Card validation runs inside `tests/test_exports.py` against a schema fixture checked
into `tests/fixtures/`, so the test does not need network access.

## Docs to update

- `README.md` — the export table; the two token estimates; the style/content
  separation, briefly.
- `docs/streamlit_app.md` — the exports selector, the dual token indicator.
- `docs/product/integrations.md` — confirm the Maya file table against what was
  actually built, and correct it if the format names changed.
- `docs/adr/0003-separate-style-from-content.md` and
  `docs/adr/0005-no-prefill-in-exports.md` — status to Accepted.

## Open questions

| Question | Decided by |
|---|---|
| Does name masking at a threshold of three occurrences remove too much from dialogue-heavy samples? | Checked against a chat-style golden sample during grounding; the threshold is a parameter, so it can be raised per sample type |
| Is the 1.3 Claude multiplier still right, or is an offline Claude tokeniser available? | Re-checked at implementation time. If a tokeniser exists, use it and delete the multiplier rather than keeping both |
| Should `voice_card` be exactly five lines or up to five? | Up to five. A profile with three strong rules should not pad |
