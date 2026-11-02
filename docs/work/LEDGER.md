# Ledger

| Spec | Size | Done | Next unit | Ground commit |
|------|------|------|-----------|---------------|
| 01-exemplars-and-rules | larger | code + tests + docs | — | `feat/v2-exemplars-and-rules` |
| 02-separation-and-exports | larger | code + tests + docs | — | `feat/v2-exemplars-and-rules` |
| 03-scorer-and-contrast | larger | code + tests + docs | — | `feat/v2-exemplars-and-rules` |
| 04-live-loop-and-evaluation | larger | code + tests | run the blind protocol | `feat/v2-exemplars-and-rules` |

## Closed

_None formally closed: all four were implemented in one pass rather than through the
spec-driven-sessions loop, so none has a `grounding.md` or a `plan.md`. That is a
deviation from this folder's own process and is recorded here rather than hidden._

## State

All four specs' code is built, tested and documented. 193 tests pass, of which the
original 77 pass **unchanged** — `build_profile(analyser)` with no v2 arguments still
returns the v1 dictionary.

What landed:

| Module | Holds |
|---|---|
| `passages.py` | Segmentation, with the hard-wrapped versus chat-shaped decision |
| `features.py` | 36 scalar features, per document and per passage |
| `baseline.py`, `data/baseline.json` | The generic-prose null hypothesis |
| `exemplars.py` | Typicality, distinctiveness, diversity; the greedy order |
| `rules.py` | 24 per-feature renderers, suppression, bands |
| `separation.py` | Style/content filters, name masking |
| `profile.py` | The frozen `Profile`, the presets, serialisation |
| `exports.py` | Five targets, two partials, the ceiling, the dual token count |
| `scorer.py` | `score`, drift, the copying check |
| `contrastive.py` | Static notes; the live tier with an injected model call |
| `cli.py` | `profile` / `render` / `score` / `card` |
| `scripts/` | `build_baseline.py`, `fetch_fixtures.py` |

Fixtures: four golden samples from Project Gutenberg with provenance files (London
31,824 words, James 42,277, Twain 111,085, Wilde 20,714), a baseline corpus, and the
Character Card V2 schema.

## What is outstanding

Two things, both about evidence rather than code.

**The blind protocol has not been run.** It needs three or more readers per author and
cannot be automated. Until it does, these ship as intuitions with defaults: the
0.4/0.4/0.2 selection weights, whether Compact carries passages, the three-occurrence
masking threshold, the twelve-word copying threshold. See [../evals/](../evals/).

**The baseline is provisional.** Hand-written, about 4,000 words against an intended few
hundred thousand of real model output. `scripts/build_baseline.py --check` reports 24 of
36 feature spreads above the 5% stability tolerance. Rule suppression is therefore
conservative and some salience figures are inflated. The refresh procedure is in
[../how-to/refresh-the-baseline.md](../how-to/refresh-the-baseline.md).

Neither blocks use of the tool. Both bound how much weight its numbers can carry, which
is why the README, the app and the baseline file all say so.

## Notes

Eight implementation deviations from the specs are recorded in
[../specs/README.md](../specs/README.md) — the two that matter most are that the
passage-size window and the no-splitting rule are not jointly satisfiable (D4), and
neither are the presets' token budgets and their exemplar counts (D5).
