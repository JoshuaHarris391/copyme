# Spec 04 — The live loop and the evaluation protocol

| | |
|---|---|
| Status | Blocked on spec 03 |
| Depends on | [Spec 03](03-scorer-and-contrast.md) — the live tier is `score()` in a loop |
| Gate | Blind pick rate 70% or lower on Standard profiles. **This is the v2 release gate** |
| Needs | An API key (`ANTHROPIC_API_KEY` or equivalent) and 3 or more readers per author |

## Why

Everything before this milestone is unmeasured. The static contrastive notes predict
where a model will drift from the baseline delta; the live tier finds out where it
*actually* drifts, by asking the target model to write and scoring what comes back.

And the project needs a verdict. v2 rests on published work about imitation in general,
not on any evidence about copyme in particular. This milestone produces that evidence,
and it can come back negative.

## Scope

1. The live contrastive tier: a small loop run once at profile time and cached.
2. The model-mismatch warning.
3. Confirm the golden-sample authors and freeze the fixtures.
4. The evaluation protocol, recorded in `docs/evals/`.
5. Decide the parameters spec 01 to 03 deliberately left open.

## Out of scope

- Any architectural change. If the gate fails, what gets revisited is the selection
  weights and the rules renderer — see "If the gate fails" below.
- Fine-tuning. It is the thing the research says would work on expert readers, and it
  is permanently out of scope for copyme. See
  [../product/non-goals.md](../product/non-goals.md).
- LLM-judge scoring as a gate. It may be collected; it decides nothing.

## Design

### The live contrastive tier

Run once at profile time, cached in the JSON so no later render costs an API call:

1. **Hold out two passages the selector did not choose.**
2. Ask the target model, with the current pre-prompt, to write on each held-out
   passage's subject at the same length.
3. Run `score` on each draft against the author.
4. Emit a known-failure note per draft from the scorer's summary, paired with the
   draft's opening sentences and the real passage's opening sentences.

Two constraints come straight from the research:

- **Corrections built against one model transfer poorly to another.** The live tier
  records which model it ran against, and the UI warns when the user pastes into a
  different one. The static tier stays the default precisely because it has no model
  dependency.
- **Smaller models sometimes imitate the bad example rather than avoid it.** The
  Compact preset carries only the correction text, never the failed draft. This was
  already true in spec 03 and must survive the live tier.

The API key is read from the environment. It is never written into a profile, a cache
file, an export footer or a log line — the footer records the **model name** only.

### Golden samples

Three public-domain authors with distinct voices, in `tests/fixtures/`, each 20,000
words or more. Proposed in spec 01, confirmed here.

| Voice | Proposed author | Why |
|---|---|---|
| Spare and plain | Jack London | Short declaratives, concrete nouns, little hedging |
| Ornate | Henry James | Long subordinated sentences, heavy parenthesis |
| Conversational | Mark Twain | First person, idiomatic, fragments and asides |

All three died more than 70 years ago, so the texts are out of copyright in both the UK
and the US. Each fixture records its source edition, so provenance survives into the
repository — the same standard the tool asks of its users.

Rules and chosen exemplars are snapshotted per author. A change to either is a reviewed
diff, not silent drift.

### The evaluation protocol

Recorded in `docs/evals/<date>-<version>.md`, one file per release, with the numbers in
a table rather than prose.

1. For each golden author, hold out **one whole work**. Profile the rest at Standard.
2. Generate five passages per author on **held-out topics** with the target model,
   using the v1 pre-prompt and the v2 pre-prompt.
3. Score every passage. Record `in_band`, copied spans, and embedding similarity if the
   extra is installed.
4. **Blind pairwise test:** 10 pairs per author (real against v2), 3 or more readers
   who know the author. Record the pick rate.
5. **Drift:** a 20-turn scripted conversation per author, scored at turns 1, 8, 16 and
   20, with and without voice-card re-pasting at turns 8 and 16.

Whole held-out works and unfamiliar topics are deliberate: they stop *recalling the
sample* passing as *imitating its style*. Running v1 alongside v2 in step 2 is what
makes the result a comparison rather than a number.

### Parameters decided here

Each of these shipped as a parameter with an intuited default. This milestone replaces
the intuition with a measurement, and records the decision in the spec folder's
deviation table or an ADR, whichever fits.

| Parameter | Default shipped | Decided by |
|---|---|---|
| Selection weights | 0.4 typicality, 0.4 distinctiveness, 0.2 diversity | Blind pick rate across weight settings on the golden samples |
| Exemplars in Compact | 3 to 5 | Pick rate for Compact with and without exemplars |
| MTLD or MATTR | Whichever spec 01 chose | Stability across sample lengths, already measured; confirmed here |
| Name-masking threshold | 3 occurrences | Whether dialogue-heavy samples lose too much |
| Copying threshold | 12 consecutive words | False-positive rate on quotation-heavy authors |

## Acceptance criteria

Live tier

- [ ] The loop runs once per profile and its output is cached in the JSON; a second
      render makes no API call.
- [ ] The held-out passages are ones the selector did not choose, verified by identity
      against the selection.
- [ ] The profile records the model the live tier ran against.
- [ ] Rendering a live-tier profile for a different model surfaces a warning in both
      the UI and the CLI.
- [ ] No API key appears in any profile, cache file, export or log line.
- [ ] With no key present, `contrastive="live"` degrades to `"static"` with a stated
      reason rather than failing.

Evaluation

- [ ] Three golden authors are frozen in `tests/fixtures/`, each 20,000 words or more,
      each recording its source edition.
- [ ] Rule and exemplar snapshots exist per author and are checked in CI.
- [ ] `docs/evals/` holds one file for this release with all five protocol steps
      recorded, including the v1 comparison.
- [ ] Blind pick rate is recorded per author and in aggregate, with the number of
      readers.
- [ ] Drift scores at turn 20 are within 10% of turn 1 with voice-card re-pasting, and
      the without-re-pasting figure is recorded alongside for contrast.

Release gate

- [ ] Aggregate blind pick rate on Standard profiles is **70% or lower**.
- [ ] No golden author shows a copied span of 12 or more words in any generated
      passage.
- [ ] Every parameter in the table above has a recorded decision, even where the
      decision is "the default stands".

## Verification

```bash
poetry run python3 -m pytest -q
poetry run python3 -m pytest tests/test_live_contrastive.py -q      # mocked; no network
poetry run copyme profile tests/fixtures/london.txt --out /tmp/london.json \
    --contrastive live --model claude-sonnet-5                      # needs ANTHROPIC_API_KEY
```

The unit tests mock the model call. The only step that needs a key is the real profile
run, and the only step that needs other people is the blind test.

## Docs to update

- `README.md` — the measured result, with the pick rate stated plainly, whether or not
  it is flattering.
- `docs/product/success-and-evaluation.md` — replace the target with the achieved
  number; keep the target visible for comparison.
- `docs/product/research.md` — add nothing unless new work was reviewed.
- `docs/evals/<date>-<version>.md` — new, the protocol run itself.
- A new ADR if the gate fails and the design changes in response.

## If the gate fails

The architecture is not what gets revisited. The four-part profile and
exemplars-over-descriptions rest on published work; the weights and the rule phrasings
rest on nothing but intuition until this milestone reports.

In order:

1. Re-run the blind test across selection-weight settings.
2. Re-phrase the rules that drifted most, and re-run.
3. Only if both fail, reopen [ADR 0001](../adr/0001-exemplars-over-descriptions.md)
   with the numbers attached.

Publishing a failing pick rate is a valid outcome of this milestone. The
[non-goals](../product/non-goals.md) already say copyme does not aim to fool an expert;
a number that shows exactly how far short it falls is more useful than silence.
