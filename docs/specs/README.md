# copyme v2 specs

One spec per milestone, executed in order. Each is written to be picked up by the
`spec-driven-sessions` workflow: ground it, plan its legs, build, review, close.

| Spec | Ships | Gate |
|---|---|---|
| [01-exemplars-and-rules.md](01-exemplars-and-rules.md) | Passage segmentation, exemplar selection, the rules renderer, the new feature set | Rule and exemplar snapshots pass on the golden samples |
| [02-separation-and-exports.md](02-separation-and-exports.md) | Style/content separation, name masking, the five export targets, dual token counts | The exported card validates against the Character Card V2 schema |
| [03-scorer-and-contrast.md](03-scorer-and-contrast.md) | `score()`, the Score tab, the baseline-refresh script, static known failures, the CLI | A text scored against its own profile is in band on every rule |
| [04-live-loop-and-evaluation.md](04-live-loop-and-evaluation.md) | The live contrastive loop, golden samples, the blind protocol | Blind pick rate 70% or lower |

Progress lives in [../work/LEDGER.md](../work/LEDGER.md). Product context is in
[../product/](../product/); the decisions these specs assume are in [../adr/](../adr/).

## Target architecture

```
                    ┌─────────────────────────────────────────────┐
 sample text  ──▶   │ StyleAnalyser  (unchanged: spaCy parse,     │
                    │ memory budget, progress, phrase cache)      │
                    └───────────────┬─────────────────────────────┘
                                    │  one parse, reused by everything below
            ┌───────────────────────┼───────────────────────┐
            ▼                       ▼                       ▼
   ┌─────────────────┐    ┌──────────────────┐    ┌──────────────────┐
   │ passages.py     │    │ features.py      │    │ vocabulary       │
   │ segment into    │    │ per-document and │    │ POS + idiom      │
   │ 120-400 token   │    │ per-passage      │    │ filters, name    │
   │ passages        │    │ feature vectors  │    │ masking          │
   └────────┬────────┘    └────────┬─────────┘    └────────┬─────────┘
            │                      │                       │
            ▼                      ▼                       │
   ┌─────────────────┐    ┌──────────────────┐             │
   │ exemplars.py    │◀───│ baseline.json    │────▶│ rules.py        │
   │ typicality +    │    │ generic-prose    │     │ suppress what a │
   │ distinctiveness │    │ feature means    │     │ model already   │
   │ + diversity     │    │ and spreads      │     │ does; emit Rule │
   └────────┬────────┘    └──────────────────┘     └────────┬────────┘
            │                                               │
            └───────────────────┬───────────────────────────┘
                                ▼
                      ┌──────────────────────┐
                      │ Profile  (frozen)    │  ◀── the contract
                      │ features, rules,     │
                      │ exemplars + reasons, │
                      │ known failures,      │
                      │ provenance           │
                      └──────┬──────┬────────┘
                             │      │
            ┌────────────────┘      └──────────────┐
            ▼                                      ▼
   ┌──────────────────────┐              ┌────────────────────┐
   │ exports.py           │              │ scorer.py          │
   │ first_message,       │              │ score(text,        │
   │ system_prompt,       │              │  against=profile)  │
   │ voice_card,          │              │ → ScoreReport      │
   │ sillytavern_card,    │              └─────────┬──────────┘
   │ json, exemplars,     │                        │
   │ rules                │                        │ feeds known
   └──────────────────────┘                        │ failures back
                                                   └───────▶ Profile
```

Two things to read off the diagram:

**The parse is still the expensive half and is still done once.** Everything
downstream re-derives from it, which is what keeps the sliders instant today and must
keep exemplar selection instant too.

**`Profile` is the only thing exports and the scorer know about.** Adding a sixth
export target must never require touching the selector or the renderer. See
[../adr/0004-profile-json-is-the-contract.md](../adr/0004-profile-json-is-the-contract.md).

## New and changed modules

| Module | State | Holds |
|---|---|---|
| `src/copyme/analyser.py` | changed, additively | New feature getters; `build_profile` gains keyword arguments |
| `src/copyme/passages.py` | new | Segmentation into candidate passages |
| `src/copyme/features.py` | new | The v2 feature set, per document and per passage |
| `src/copyme/exemplars.py` | new | `select_exemplars` and the three scores |
| `src/copyme/rules.py` | new | `Rule`, `render_rules` |
| `src/copyme/profile.py` | new | The frozen `Profile` dataclass and its serialisation |
| `src/copyme/exports.py` | new | The export renderers; `build_pre_prompt` moves here or delegates |
| `src/copyme/scorer.py` | new | `Drift`, `ScoreReport`, `score` |
| `src/copyme/contrastive.py` | new | Static and live known-failure generation |
| `src/copyme/cli.py` | new | `copyme profile / render / score / card` |
| `src/copyme/data/baseline.json` | new | Generic-prose feature means and spreads. Numbers only, no text |
| `src/copyme/pre_prompt.py` | changed | Keeps `build_pre_prompt`; the metric dictionary leaves the prompt |
| `src/copyme/metrics_dictionary.py` | changed | Stays as a reference for the UI and the JSON profile; stops being prompt content |
| `scripts/build_baseline.py` | new | Regenerates `baseline.json`. A maintenance task, not a user step |
| `streamlit_app.py` | changed | Size radio, exports selector, exemplar display, Score tab |

## Spec conventions

Every spec in this folder has the same sections, in this order:

- **Why** — the problem, in one or two paragraphs
- **Scope** / **Out of scope** — what this milestone does and explicitly does not
- **Design** — the mechanism, concrete enough to implement from
- **Public API** — signatures, exactly
- **Acceptance criteria** — testable checkboxes; these are what `review` checks
- **Verification** — the exact command
- **Docs to update** — which docs ship in the same commit as the code
- **Open questions** — what is deliberately undecided, and who decides it

Specs do not contain credentials, hostnames or real API keys. Where a spec needs one
it names the environment variable (`ANTHROPIC_API_KEY`) and nothing else.

## Deviations from the source design document

Recorded rather than silently resolved.

| # | Source says | These specs say | Why |
|---|---|---|---|
| D1 | The baseline vector ships in milestone 3 | A provisional baseline ships in milestone 1; the regeneration script and documented refresh stay in milestone 3 | Milestone 1 cannot compute distinctiveness or suppress a rule without a baseline. Deferring it would make milestone 1 unshippable on its own, which breaks the "each milestone is useful alone" property |
| D2 | Milestone 4 holds the golden samples | The golden-sample fixtures land in milestone 1 | They are milestone 1's own gate — the rule and exemplar snapshots have nothing to snapshot without them. The blind protocol that *uses* them stays in milestone 4 |
| D3 | Part C lists Maya code changes | They are documented in [../product/integrations.md](../product/integrations.md), not specified here | They are changes to a different repository and belong in its spec folder |

## Deviations found during implementation

The four specs were implemented together rather than in sequence. These are the places
where the specs turned out to be unbuildable as written, recorded rather than quietly
resolved.

| # | Spec says | What was built | Why |
|---|---|---|---|
| D4 | Every passage is 120 to 400 tokens, except the last; and no passage splits a paragraph (spec 01) | Both rules hold except where they conflict — a single paragraph, dialogue run or list run longer than 400 tokens is emitted whole and flagged `oversized` | The two rules are not jointly satisfiable. Henry James writes paragraphs past the ceiling, and splitting one destroys the thing being measured. Overshooting is visible in the flag; a sub-floor passage would have been invisible. Segmentation also aims at 300 tokens rather than closing at the 120 floor, which stopped passages clustering at the floor and wasting the budget |
| D5 | Each preset's output is within 15% of its stated token budget (spec 01) | The budget is enforced as a **ceiling**: output never exceeds it, and may fall well under | The stated budgets and exemplar counts are not jointly satisfiable either. Full allows 20,000 exemplar tokens and 20–30 passages, but a passage is capped at 400 tokens, so 30 passages cannot exceed about 12,000. The counts come from the research on how many examples help; the budgets are limits on where a prompt has to fit. Where they conflict, overflowing the field a prompt was sized for is the harmful error and coming in short is not, so `exports.py` drops passages until the render fits |
| D6 | The scorer is spec 03; selection and rules are spec 01 | A minimal feature-distance scorer and the full v2 feature set were built first, before selection and rules | Spec 01's open questions — the selection weights, MTLD versus MATTR, whether Compact carries passages — are all answered by measurement, and spec 04 holds the measurement. Building the measurement layer first is what let MATTR be chosen on evidence (5.7% drift against MTLD's 36.9%) rather than shipped as a guess |
| D7 | `Rule.band` is "the accept range for the scorer" (spec 01), unspecified | Each band is the author's value widened by the author's **own** passage-to-passage standard deviation, falling back to ±35% where that is unknown | A flat percentage calls a consistent writer's ordinary sentence out of range and lets an erratic writer's wild swing pass. Selection already walks every passage to compute the spread, so it hands the numbers to the renderer rather than having them computed twice |
| D8 | The live contrastive tier is accepted and rejected until spec 04 lands (spec 03) | The live tier is implemented, with the model call injected as a parameter | Building all four specs together made the staged rejection pointless. Injecting the call is what lets the whole tier be unit-tested with no network and no key; only the API call itself is untested |

## What remains unbuilt

One thing in spec 04 is not code and was not done: **the blind evaluation protocol has
not been run**, because it needs three or more human readers per author. Everything that
depends on it — the selection weights, whether Compact should carry passages at all, the
name-masking threshold, the copying threshold — therefore still ships as an intuition
with a default attached. [../evals/](../evals/) records what is outstanding and what has
actually been measured.
