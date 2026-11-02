# The baseline corpus

This is the null hypothesis. Every rule copyme emits is a rule the model does
*not* already follow, and this corpus is how "already follow" is defined: a
feature within half a standard deviation of these numbers produces no rule,
because telling a model to do what it does anyway spends tokens and dilutes the
lines that matter.

`scripts/build_baseline.py` reads every `*.txt` file in this directory, splits
each on a line containing only `---`, computes the v2 feature set over each
passage, and writes the means and spreads to
`src/copyme/data/baseline.json`. Only numbers are written; no text from this
corpus ships in the package.

## Status: provisional

| | |
|---|---|
| Source | Hand-written in assistant register by the maintainer |
| Passages | 20 |
| Words | about 4,000 |
| Target | A few hundred thousand words of real model output |

Spec 01 put this on record and it still holds: the provisional baseline is good
enough to suppress rules and rank distinctiveness, and **not** good enough to
publish numbers from. Any rule phrasing tuned against it must be re-checked when
it is replaced.

The shortfall is twofold. The corpus is roughly two orders of magnitude smaller
than the target, so the spreads are wider than they should be — which makes rule
suppression conservative, erring towards emitting a rule rather than dropping
one. And it is one person's impression of how a model writes rather than a
sample of how one actually does.

## Refreshing it with real model output

The intended corpus is generated, not written. To replace this file:

1. Generate a few hundred thousand words of assistant-style prose across varied
   prompts and subjects, using the model copyme is mostly pointed at.
2. Save it here as one or more `*.txt` files, passages separated by `---`.
3. Record the model name, the date and the prompt set in `provenance.json`.
4. Delete `assistant_prose.txt`.
5. Re-run `poetry run python3 scripts/build_baseline.py --bump`, which raises the
   baseline version so existing profiles record which baseline they were built
   against.
6. Re-check every rule phrasing that was tuned against the provisional numbers.

The full procedure, including the corpus-size check, is in
[../../../docs/how-to/refresh-the-baseline.md](../../../docs/how-to/refresh-the-baseline.md).
