# Spec 03 — The scorer, the baseline and the contrastive block

| | |
|---|---|
| Status | Blocked on spec 02 |
| Depends on | [Spec 01](01-exemplars-and-rules.md) for `Rule.band`, [Spec 02](02-separation-and-exports.md) for the JSON profile |
| Gate | A text scored against its own profile is in band on every rule |
| Decisions assumed | [ADR 0006](../adr/0006-static-contrastive-by-default.md) |

## Why

Two gaps close here.

**No version of copyme has ever told a user whether it worked.** They paste a
pre-prompt, read the model's output, and judge by feel. A scorer is nearly free —
copyme can already profile any text — and it turns the tool from "here is a prompt"
into "here is a prompt, and here is what drifted".

**The model's predictable mistakes are not yet in the prompt.** The one prompting
technique with direct evidence on Claude (TICL, 2025) is to show the model an off-voice
attempt beside the real passage with a one-line explanation of the gap. The
explanations carried most of the gain. The delta between the author's feature vector
and the generic baseline already tells us where a model will drift, so the static half
of this costs no API call.

This milestone also replaces spec 01's provisional baseline with a scripted,
regenerable one.

## Scope

1. `score()`, `Drift` and `ScoreReport`, including the copying check.
2. The static contrastive tier: known-failure notes from the author-to-baseline delta.
3. `scripts/build_baseline.py` and a documented refresh, replacing the provisional
   baseline.
4. The CLI: `copyme profile / render / score / card`.
5. The Streamlit Score tab.
6. The optional `copyme[embeddings]` extra.

## Out of scope

- The live contrastive tier, which needs an API key — spec 04.
- The blind human protocol — spec 04.
- Any change to selection or rendering. If the scorer shows the rules are wrong, that
  is a finding for spec 04, not a quiet edit here.

## Design

### The scorer (`scorer.py`)

```python
@dataclass(frozen=True)
class Drift:
    feature: str
    author: float
    generated: float
    verdict: str      # "in band" | "too high" | "too low"
    note: str         # "sentences 40% longer than the author"

@dataclass(frozen=True)
class ScoreReport:
    drifts: list[Drift]
    in_band: float            # share of rules met, 0 to 1
    copied_spans: list[str]   # runs of 12+ words shared with the sample
    summary: str              # three lines for a human
```

`score(generated: str, against: Profile) -> ScoreReport` runs the same feature
extraction on the model's output and compares each feature with the author's
`Rule.band`.

`score` is **pure**: no model, no network, no file writes. That is a test, not just an
intention.

**The summary is written in the form a correction would take** — "sentences 40%
longer; hedging doubled; no sentence opened with *And*" — because it feeds the
contrastive block directly. A summary phrased as a measurement would need rewriting
before it could be used.

**The copying check** flags any run of 12 or more consecutive words shared between the
output and the sample, enforcing the no-reproduction instruction that spec 02 added but
could not check.

**What the report does not claim**, stated in its own footer: the scorer measures the
habits copyme can measure. A passage can pass every band and still not sound right, and
classifier-style agreement can coexist with prose far more predictable than the
human's. The blind test stays the arbiter.

### The static contrastive tier (`contrastive.py`)

No API key needed. The author-to-baseline delta says where a model will drift, so the
renderer writes one known-failure note per large delta, phrased so the model recognises
the habit as its own:

> **Likely drift:** a draft in this voice tends to run longer, hedge more and close
> each paragraph with a summarising sentence. The author stops when the point is made
> and leaves the implication standing.

**Three notes at most, ranked by delta size.** The 2025 human study found that "AI-ish"
habits such as cliché density explained a measurable share of why readers rejected
prompted imitation, so naming the specific habits is worth the tokens — but three is
where the budget stops paying.

The Compact preset includes **only the correction text, never a failed draft**, because
smaller models sometimes imitate the bad example rather than avoid it.

### The baseline (`scripts/build_baseline.py`)

`src/copyme/data/baseline.json` holds **feature means and spreads only — no text**. It
ships in the package because distinctiveness and rule suppression need it at import
time.

The script rebuilds it from a corpus of assistant-style output, roughly a few hundred
thousand words. Regenerating is a documented maintenance task, not a user step, and the
baseline carries a version recorded in every profile so an old profile can be read
against the baseline it was built with.

Replacing spec 01's provisional baseline is part of this milestone, and **every rule
phrasing tuned against the provisional one is re-checked** when it lands.

### The optional embedding check

Behind an extra, `copyme[embeddings]` adds a content-independent style embedding
(StyleDistance or the Wegmann model, both small enough for CPU) and reports cosine
similarity between generated text and the author's centroid.

It is a second opinion, not the score. It stays optional because it is **the only part
of copyme that downloads a model**, and `score()` must keep working with no network.

### The CLI (`cli.py`)

A thin wrapper, Typer or argparse. No logic lives here.

```bash
copyme profile sample.txt --out profile.json [--budget 5000] [--contrastive live --model claude-sonnet-5]
copyme render profile.json --size standard --format system_prompt
copyme score generated.txt --against profile.json [--json]
copyme card profile.json --out author.png          # SillyTavern V2 card with embedded JSON
```

`--contrastive live` is accepted and rejected with a clear message until spec 04 lands.

### The Streamlit Score tab

The same `score()` call, nothing special. Paste the model's output, see the drift lines,
the copied spans and the footer caveat. The exemplar selection is cached per
`(budget, percentile, mask_names)` the same way phrase counts are cached today, so
switching tabs never re-parses.

## Public API

```python
from copyme import score, ScoreReport, Drift

report = score(generated_text, against=profile)
print(report.summary)

build_profile(
    analyser,
    ...,
    contrastive: str | None = "static",   # "static" | "live" | None
    model: str = "claude-sonnet-5",       # recorded; used by "live" in spec 04
)
```

## Acceptance criteria

Scorer

- [ ] A text scored against its own profile is in band on every rule.
- [ ] A text with a 12-word span copied from the sample is flagged in `copied_spans`;
      an 11-word span is not.
- [ ] `score` is pure: a test with network access removed and the filesystem read-only
      passes.
- [ ] `in_band` is the share of rules met and equals 1.0 exactly when `drifts` contains
      no non-"in band" verdict.
- [ ] Every `ScoreReport` carries the footer caveat, in every render.
- [ ] The summary reads as a correction, not a measurement — snapshotted on the golden
      samples so a rewording is a reviewed diff.

Contrastive

- [ ] At most three known-failure notes, ordered by delta size, deterministic for a
      fixed profile.
- [ ] The Compact preset contains no failed-draft text.
- [ ] A profile whose features are all within half a standard deviation of baseline
      emits no notes, and the prompt's known-failures section is absent rather than
      empty-with-a-heading.

Baseline

- [ ] `baseline.json` contains no text field — numbers, feature names and a version
      only.
- [ ] `scripts/build_baseline.py` regenerates it reproducibly from a named corpus, and
      the run is documented.
- [ ] Every profile records the baseline version it was built against.

CLI

- [ ] All four subcommands run end to end on a golden sample.
- [ ] `copyme score --json` emits valid JSON on stdout with no log lines mixed in.
- [ ] `--contrastive live` fails with a message naming spec 04, not a traceback.
- [ ] No subcommand requires an API key.

## Verification

```bash
poetry run python3 -m pytest tests/test_scorer.py tests/test_contrastive.py tests/test_cli.py -q
poetry run python3 -m pytest -q
poetry run copyme score tests/fixtures/generated_sample.txt --against tests/fixtures/profile.json
```

## Docs to update

- `README.md` — the scorer, the CLI, the embeddings extra and what it downloads.
- `docs/streamlit_app.md` — the Score tab.
- `docs/product/success-and-evaluation.md` — confirm the three cheaper checks against
  what the scorer actually reports.
- A new `docs/how-to/refresh-the-baseline.md` — the maintenance procedure, with exact
  commands. This is the one recurring manual task v2 introduces.
- `docs/adr/0006-static-contrastive-by-default.md` — status to Accepted.

## Open questions

| Question | Decided by |
|---|---|
| Is "no run of 12 or more consecutive words" the right copying threshold? | Measured on the golden samples. A quotation-heavy author may trip it legitimately, in which case quoted spans are excluded rather than the threshold raised |
| How large must the baseline corpus be before the spreads stabilise? | Empirically, during the script's first run: increase the corpus until feature spreads move less than 5% between halves |
| Which embedding model — StyleDistance or Wegmann? | Whichever agrees better with the blind-test results in spec 04. Until then ship StyleDistance and record the choice |
| Does the baseline age fast enough to need more than a yearly refresh? | Re-checked at the first refresh. The risk is recorded in [../product/roadmap.md](../product/roadmap.md) as medium and slow |
