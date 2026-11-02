# What the user does

The Streamlit flow keeps its one-button shape. It gains a size choice, a scorer and
more export targets.

## 1. Paste a sample

As now. The guidance changes.

Today the app says "a few paragraphs is enough". v2 says **2,000 words gives a
recognisable voice; 10,000 or more gives a reliable one**, because exemplar selection
needs passages to choose between. Below about 2,000 words the app says so rather than
producing a confident profile from thin evidence.

The memory-budget control and the two vocabulary sliders are unchanged.

## 2. Generate the profile

The same progress container, with two new stages: **Choosing exemplars** and **Writing
voice rules**.

## 3. Pick a size

Three presets, each sized for where the profile is going:

| Preset | Budget | Contents | Use |
|---|---|---|---|
| Compact | about 2k tokens | Rules, voice card, 3 to 5 short exemplars | A system prompt field |
| Standard | about 8k tokens | 10 to 15 exemplars | Pasting into a chat |
| Full | up to 30k tokens | 20 to 30 exemplars | Long-context models, Claude Projects |

The sidebar keeps the vocabulary percentile and phrase-length sliders, which re-derive
from the cached parse as they do today.

## 4. Read the profile

The app shows three things, in this order:

1. The **exemplars it chose, and why** — each carries a one-line reason, such as
   "typical of the author; unlike generic prose; the only conversational passage".
   The reason is for the user; it is never sent to the model.
2. The **voice rules** in plain language.
3. The **raw metrics**, in a collapsed section. Nothing is taken away from the user;
   it just stops being the prompt.

## 5. Copy, in the format needed

| Target | Shape |
|---|---|
| `first_message` | Markdown block, as today — paste as the first message of a chat |
| `system_prompt` | The same without the "you are about to" framing, written as standing instructions |
| `voice_card` | Five lines, for re-pasting mid-conversation |
| `sillytavern_card` | Character Card V2 JSON |
| `json` | The full profile: features, rules with bands, exemplars with reasons, known failures, provenance |

Every export carries a provenance footer: the copyme version, the profile hash, the
sample's word count, and the model the live contrastive tier ran against, if any. That
footer is what lets a user tell two profiles apart six months later.

## 6. Score the result

A new **Score** tab. Paste back what the model wrote; copyme profiles it and reports
which habits drifted:

> sentences 40% longer than the author; hedging doubled; no sentence opened with *And*

Those lines are deliberately written in the form a correction would take, because they
are the start of the next, better prompt. The scorer is also how a user knows the tool
worked for *their* author, which no version of copyme has offered.

The report says plainly what it does not claim: a passage can pass every band and still
not sound right. See [success-and-evaluation.md](success-and-evaluation.md).

## The same steps as functions

```python
from copyme import StyleAnalyser, build_profile, build_pre_prompt, score

analyser = StyleAnalyser(sample)          # expensive, as now
profile = build_profile(analyser, exemplar_budget=5_000, mask_names=True)

text = build_pre_prompt(profile, size="standard", format="first_message")
report = score(generated_text, against=profile)
print(report.summary)
```

A CLI covers the same ground for scripting: `copyme profile`, `copyme render`,
`copyme score`, `copyme card`. Signatures are specified in
[../specs/02-separation-and-exports.md](../specs/02-separation-and-exports.md) and
[../specs/03-scorer-and-contrast.md](../specs/03-scorer-and-contrast.md).
