# Roadmap

Four milestones. Each ships on its own and is useful alone, and each has a gate that
can fail.

```
1 Exemplars + rules  ──◇──  2 Filter + exports  ──◇──  3 Scorer + contrast  ──◇──  4 Live loop + evals  ──◆
   segment + select           POS + name filters         score(), Score tab          live contrastive
   rules renderer             system prompt, card        baseline refresh            golden samples
   new features, MTLD         SillyTavern V2, JSON       static failures, CLI        blind protocol

   ◇ snapshots pass           ◇ V2 card validates        ◇ in band on goldens        ◆ pick rate 70% or less
```

| # | Milestone | Useful alone because | Gate |
|---|---|---|---|
| 1 | Exemplars and rules | The pre-prompt already carries the author's real passages and followable rules | Rule and exemplar snapshots pass on the golden samples |
| 2 | Separation and exports | The profile reaches Maya, SillyTavern and any system-prompt field | The exported card validates against the Character Card V2 schema |
| 3 | Scorer and contrastive block | A user can check whether their own result landed | A text scored against its own profile is in band on every rule |
| 4 | Live loop and evaluation | The release gate itself | Blind pick rate 70% or lower |

## Sizing

One engineer working evenings and weekends: **one to two weekends per milestone**.

Milestones 1 to 3 need nothing but the repo. Milestone 4 is the only one that needs an
API key (for the live contrastive tier) and other people's time (for the blind test),
which is why it is last rather than interleaved.

## Where the risk sits

Milestone 1 carries the design risk: the selection weights (0.4 typicality, 0.4
distinctiveness, 0.2 diversity) and the rule phrasings are the parts resting on
intuition rather than published work. They are exposed as parameters precisely so
milestone 4 can tune them without reopening the architecture.

Milestone 4 carries the schedule risk: the blind test depends on readers who know the
chosen authors, and it can fail. See
[success-and-evaluation.md](success-and-evaluation.md).

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Exemplars still read as "AI doing an impression" to readers who know the author | High — the strongest human study found only fine-tuning convinced expert readers | Set the bar at recognisable, not undetectable; publish the blind-test numbers either way |
| Users paste in-copyright text and publish the result | Medium | README guidance; the provenance footer; no feature that strips attribution |
| Live contrastive notes tuned on one model mislead on another | High if ignored | Record the model; warn on mismatch; keep the static tier as the default |
| The baseline vector ages as assistant prose changes | Medium, slow | Regenerate yearly from a documented script; version it in every profile |
| The scorer passes text that still sounds wrong | Certain for some texts | The scorer is a gate on habits, not a verdict; the human test stays the arbiter |

## Open questions

Carried deliberately rather than guessed. Each is listed against the spec that decides
it.

- Are the 0.4 / 0.4 / 0.2 selection weights right? Decide from the golden-sample blind
  tests, not from intuition.
- Should Compact include any exemplar at all, or only rules and the voice card? The
  research favours even three short exemplars; measure it.
- Is a Claude tokeniser available offline for an exact count, or does the 1.3
  multiplier stand?
- Does name masking at a threshold of three occurrences remove too much from
  dialogue-heavy samples?

## The specs

Each milestone is one spec file, in [../specs/](../specs/):

1. [01-exemplars-and-rules.md](../specs/01-exemplars-and-rules.md)
2. [02-separation-and-exports.md](../specs/02-separation-and-exports.md)
3. [03-scorer-and-contrast.md](../specs/03-scorer-and-contrast.md)
4. [04-live-loop-and-evaluation.md](../specs/04-live-loop-and-evaluation.md)

Progress is tracked in [../work/LEDGER.md](../work/LEDGER.md).
