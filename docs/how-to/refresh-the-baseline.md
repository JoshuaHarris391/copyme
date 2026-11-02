# How to refresh the generic-prose baseline

This is the one recurring manual task v2 introduces. It is a maintenance job, not
something a user of the app ever does.

## What the baseline is for

copyme only tells a model to do something if the model would not already do it. A
feature within half a standard deviation of the baseline produces **no rule**, because
the model's default is already right and every extra line dilutes the ones that matter.
The baseline is also what "unlike generic prose" means when a passage is scored for
distinctiveness.

So the baseline is a null hypothesis, and it has to be a sample of what a model writes
unprompted — not a sample of generic *human* prose, which is a different distribution
and would suppress the wrong rules.

`src/copyme/data/baseline.json` holds feature means and spreads only. No text from the
corpus ships in the package.

## Current status: provisional

| | |
|---|---|
| Source | Hand-written in assistant register by the maintainer |
| Size | 20 passages, about 4,000 words |
| Target | A few hundred thousand words of real model output |
| Spreads above the 5% stability tolerance | 24 of 36 |

The consequences are worth being specific about:

- **Rule suppression is conservative.** Wider spreads mean fewer features clear the
  distinctiveness threshold in one direction and more in the other; in practice copyme
  errs towards emitting a rule rather than dropping one.
- **Salience figures are inflated** for features the small corpus barely exercises.
  First-person rate is the clearest case: the corpus almost never writes as *I*, so any
  first-person author scores an implausibly large deviation.
- **Numbers from it should not be published.** It is good enough to rank passages and
  filter rules. It is not evidence about how models write.

Any rule phrasing tuned against these numbers must be re-checked when they are
replaced.

## When to refresh

- When the corpus is replaced with real model output. This is the one that matters.
- When a feature is added to `FEATURE_NAMES`. A feature with no baseline cannot be
  suppressed or ranked, and `tests/test_baseline.py` fails until the baseline covers it.
- When the model families copyme is mostly pointed at change materially. The risk is
  recorded as medium and slow in [../product/roadmap.md](../product/roadmap.md); a
  yearly check is the current assumption, and the first refresh should test it.

## The procedure

### 1. Generate the corpus

A few hundred thousand words of assistant-style prose, across varied prompts and
subjects, from the model copyme is mostly pointed at. Vary the subject matter
deliberately: the current corpus is all software and technical explanation, which skews
the opener and vocabulary features even though the register features survive it.

### 2. Put it in place

Save it as one or more `*.txt` files in `tests/fixtures/baseline_corpus/`, with
passages separated by a line containing only `---`. Delete `assistant_prose.txt`.

Record what it is in `tests/fixtures/baseline_corpus/provenance.json`: the model name,
the date, the prompt set, the word count, and `"status": "measured"`.

### 3. Check the corpus is large enough

```bash
poetry run python3 scripts/build_baseline.py --check
```

This writes nothing. It computes the feature spreads over the first half of the corpus
and the second half and reports the worst difference between them. While any feature is
above the 5% tolerance, the corpus is too small for that spread to be trusted — add
more and re-run.

Do not skip to step 4 because the number is "close enough". The whole value of the
baseline is that it is a stable description of what a model does; an unstable one
produces rule sets that change when the corpus does, for no reason the user can see.

### 4. Regenerate

```bash
poetry run python3 scripts/build_baseline.py --bump
```

`--bump` raises the baseline version. Use it whenever the numbers change materially:
every profile records the baseline version it was built against, so an old profile
stays interpretable rather than looking simply wrong.

### 5. Re-check the rule phrasings

The rules were written against the provisional numbers, and some of them were tuned to
read well at those salience levels. Build a profile for each golden sample and read the
rules:

```bash
poetry run python3 -m copyme.cli profile tests/fixtures/london.txt --out /tmp/l.json --quiet
poetry run python3 -m copyme.cli render /tmp/l.json --format rules
```

Look for rules that now read as overclaims or that have disappeared, and for salience
figures that have moved by an order of magnitude.

### 6. Run the tests

```bash
poetry run python3 -m pytest -q
```

`tests/test_baseline.py` asserts that the shipped baseline declares itself provisional
while its spreads are unstable. Once the corpus is large enough that they are stable,
that test is expected to fail — update it to assert `"measured"` instead, which is the
point at which the status in this document and in the README should change too.
