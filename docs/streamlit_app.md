# Streamlit App: Linguistic Profile Generator

A UI for building a writing-voice profile from a sample and rendering it wherever a
voice is needed. Paste a sample, pick a size, read the passages it chose and the rules
it wrote, and copy the result in the format you need.

## Prerequisites
- Python `>=3.10,<3.14`
- Poetry installed

## Setup
From the project root:

```bash
poetry install
```

## Run the app
From the project root:

```bash
poetry run streamlit run streamlit_app.py
```

## Use the app
1. Optionally set the **Temporary memory budget (GB)** in the sidebar. The sidebar shows the resulting **Maximum text length** in characters and the length of the current input.
2. Paste or type text into the **Text to analyze** input. Aim for 2,000 words or more.
3. Choose a **Profile size** and decide whether to **mask one-off names**.
4. Click **Generate linguistic profile**.
5. On the **Profile** tab, review in order:
   - **The passages it chose, and why** — each in an expander, with its reason and its three scores
   - **Voice rules**
   - **Where this usually goes wrong**, when there is predictable drift to report
   - **Copy it, in the format you need** — the format selector, the dual size indicator, and the copyable block
   - **Raw metrics**, collapsed
6. On the **Score a draft** tab, paste what the model wrote and click **Score it**.

## Profile size

The sidebar's **Size** radio chooses between three presets.

| Preset | Ceiling | Passages | For |
|---|---|---|---|
| Compact | 2,000 tokens | 3–5 | A system-prompt field |
| Standard | 8,000 tokens | 8–15 | Pasting into a chat |
| Full | 30,000 tokens | 15–30 | Long-context models, Claude Projects |

The token figure is a **ceiling, not a target.** A prompt that overflows the field it
was sized for is silently truncated by whatever it was pasted into — the user sees a
complete profile and the model sees half of one — so passages are dropped from the end
of the selection until the rendered prompt fits. Full usually lands well under its
ceiling, because 30 passages capped at 400 tokens each cannot fill 30,000 tokens.

Raising the size always returns a **superset** of the passages a smaller size chose, in
the same order, so nudging the radio never silently swaps out a passage you had already
read and approved.

## The passages, and their reasons

Each selected passage is shown in an expander labelled with a one-line reason — *"typical
of the author; semicolons well above generic prose"* — and its typicality,
distinctiveness and diversity scores.

**The reason is never sent to the model.** It exists so a person can audit the
selection, which is a different job from prompting: a model shown "chosen because it is
the only conversational passage" may imitate the explanation rather than the passage.

## Masking one-off names

On by default. A name appearing fewer than three times is replaced by a role
placeholder — `[a person]`, `[a city]` — so a passing mention of a third party cannot
leak into every generation. Names the author uses throughout are kept: they are part of
the author's recurring world, and the research found masking those costs style learning
nothing while removing something real from the voice.

Masking is **best-effort, not redaction.** It can only replace what spaCy's small
English model recognises as an entity, and that model misses names — particularly
unusual given names, and any capitalised word at the start of a sentence. Where a name
must not appear, it should not be in the sample.

Turning the toggle off returns the source passages byte for byte, with no re-parse: both
forms are stored on the profile.

## Scoring a draft

The **Score a draft** tab compares what the model wrote against the author on every
rule the profile set, and checks that nothing was lifted.

- **Rules met** is the share of rules whose band the draft landed inside. Each band is
  centred on the author's own value and widened by the author's own passage-to-passage
  variation, so "in band" means "within this author's natural range" rather than within
  an arbitrary percentage.
- The table lists every rule with the author's value, the draft's value, a verdict and a
  note phrased as a correction — *"sentence length 40% longer than the author"*.
- **Copied spans** flags any run of 12 or more consecutive words shared with the sample.
  The prompt tells the model not to do this; until v2 nothing checked.

The report carries a footer in every render, and it is there for a reason: a passage can
pass every band and still not sound right. The bands cover the habits copyme can
measure. A blind read stays the arbiter — and the **Blind test** page is where one is
run.

## The Blind test page

A second page in the app, listed in the sidebar. It exists because the scorer above
cannot settle copyme's actual claim: it checks whether a draft hits the measurements
copyme itself chose, which is circular. The blind test asks people instead, by showing a
reader a real passage and a generated one without saying which is which.

It has its own page rather than a tab for a practical reason: a reader judging
comparisons has no writing sample to paste and no reason to wait for spaCy, and the
profiler gates everything behind that parse.

Two modes:

| Mode | Who | What they get |
|---|---|---|
| **Run a blind test** | A reader | Generated comparisons, judged one at a time, then a pick rate and four files |
| **Tally the results** | Whoever pools readers | One pick rate across several readers' ballots, with its confidence interval |

### Running one

In the profiler, open **For the blind test** and copy the block without reading it. That
is the profile JSON, and the instruction is not a formality: it names which passages are
the author's own, so a reader who has read it will recognise them on the cards and
measure their own memory rather than the profile.

Paste it on the Blind test page, name yourself and the author, and press **Generate and
start**. The app renders the prompt, asks the model to write one passage per round, and
pairs each with a real passage. Then it shows one comparison at a time: two passages
side by side, Left, Right or Skip, and Next.

The generated side used to be produced by hand — render the prompt, paste it into a
chat, ask for a passage, copy the reply back — sixty round trips for a full three-author
run, which is why no run was ever recorded. That step is now the **Generate and start**
button.

What gets pasted is the JSON rather than the rendered prompt, and the reason is
structural: the prompt carries only the passages the profile chose, and those are
exactly the ones unusable as the real side of a comparison. A model asked to write on the
subject of a passage sitting in its own instructions is being tested on recall. The JSON
carries the whole passage ranking, so the page can render the prompt *and* draw real
passages from the ones the prompt left out.

Three things about it are deliberate.

**Nothing is revealed until the run ends.** Per-card feedback would teach a reader the
imitation's tells on card one and let them apply it to card nine, pushing the pick rate
up for reasons that have nothing to do with the profile. The answer key is in session
state from the moment generation finishes, and the judging screen renders no metric and
no verdict — a run's own test suite asserts it. When the run ends, every card is opened
up with the real side named, which is where the tells are worth learning.

**The whole run is generated before any of it is judged.** So the key is complete and
seeded before the first card appears, and the side each passage lands on is the same
seeded coin flip a mailed-out packet uses.

**The packet and the key are separate files.** The packet a reader receives contains the
passages and no record of which side is real — the shuffle seed included, because the
seed plus the published algorithm would be enough to reconstruct the answers. Blindness
is therefore structural rather than a matter of the reader's discipline, which is not
true of any single-file format.

**Every result carries a confidence interval, and the gate is judged on it.** 10 pairs
and 3 readers is 30 judgements, and a pick rate of 70% from 30 judgements has a 95%
interval of roughly 52% to 84%. So a run whose point estimate sits at or under the 70%
gate is *not* reported as meeting it unless the whole interval does; the verdict says
there are too few judgements to call instead. Reading the point estimate alone is how a
blind test gets over-interpreted, and the page is built to make that hard.

Remember the direction: **a lower pick rate is better.** 50% is a coin flip and the
ceiling of what imitation can achieve; 100% means readers spot the imitation every time.

What the page cannot supply is the readers. The protocol asks for three or more per
author who know that author's writing, and a run with fewer is labelled indicative
rather than reported as a result. See [evals/](evals/).

Reaching three means three people each running their own test. Each run generates its
own passages, so their packets differ and their ballots cannot be tallied against one
key — the pick rates have to be pooled across runs, with each run's own result file
kept. **Tally the results** still combines several ballots against a *single* packet,
which is what to use when the same comparisons are judged by more than one person, or to
re-score a run from its files.

### What a run leaves behind

Four files, the same four a mailed-out run produces:

| File | What it is for |
|---|---|
| `<id>-result.json` | The number, its interval and the run's parameters. One per run in [evals/](evals/) |
| `<id>-packet.json` | The comparisons, with no record of which side is real |
| `<id>-key.json` | Which side was real, plus the shuffle seed |
| `<id>-ballot-<reader>.json` | One reader's picks |

### The API key

Generation reads **`COPYME_ANTHROPIC_API_KEY`** from the environment the app was started
in. There is no field for it in the UI, and it is never written into a profile, a packet,
a result or a log line — the result records the model's *name* and nothing else.

The variable is deliberately not the SDK's own `ANTHROPIC_API_KEY`: a key set in the
shell for some other tool is not consent for a Streamlit page to spend it. The CLI's
`--contrastive live` still uses `ANTHROPIC_API_KEY`, so the two surfaces read different
names.

## Status indicator
While the analysis runs, the app shows a status container that reports the current stage, a progress bar, and the elapsed time. Two of the stages are new in v2 — **Choosing exemplars** and **Writing voice rules** — and the app opts into them by passing `V2_ANALYSIS_STAGES` to the analyser, so the bar is scaled for the work that is actually going to happen rather than stopping at 94%. Stages are reported by the analyser through the same `on_progress` callback the library exposes, so the UI and any notebook or script see identical progress values. When the run finishes the container collapses to *Analysis complete in Ns*; if the input is rejected for being too long it turns into an error state instead.

## Vocabulary percentile

The sidebar's **Keep the most frequent (%)** slider sets how much vocabulary is captured. Words and phrases are ranked by frequency and trimmed to the most frequent share of distinct terms, truncated independently, with a default of 20%.

The knob is proportional rather than absolute, so the same setting yields a handful of terms on a short sample and a large list on a long document. At least one term is always kept, and raising the slider always returns a superset of the lower setting.

**This no longer feeds the prompt.** In v1 the vocabulary list was a prompt section; in
v2 it is not, because on any real sample most of a frequency list is the sample's
*subject* rather than the author's manner — a profile of someone's work email produced a
model that kept mentioning the quarterly report.

The slider now drives the vocabulary tables in **Raw metrics** and the `words` section
of the v1 metrics the profile retains. The prompt instead carries a **style
vocabulary**: the author's connectives and qualifiers, plus their repeated idioms,
filtered so that *"I mean"* survives and *"the quarterly report"* does not. That filter
is not adjustable from the sidebar.

## Phrase length

The **Longest phrase (words)** slider sets the maximum phrase length, from 2 to 6 words, defaulting to 4. Phrases are repeated word sequences, so 2 captures pairs like *of the* while 5 can capture *in the end of the*. Longer sequences repeat far less often, so raising the slider mostly reshuffles the shorter candidates.

The slider changes the phrase list and the idiom candidates. It deliberately does **not** change Formulaic Density: that metric measures the proportion of the text made of repeated 2-4 word sequences and is scored against fixed bands, so letting a slider move it would make profiles incomparable. The metric stays pinned to 2-4 words, whatever the slider says. The active length is recorded in `results["limits"]["max_phrase_words"]` for reproducibility.

Like the vocabulary slider, this re-derives from the cached parse. Repeat calls for the same range are memoised on the analyser, so moving the slider costs a few milliseconds even on a long document.

## Why the slider does not re-parse

Parsing is the expensive half of the analysis — roughly 4 seconds for a 199,000-character sample — while re-selecting the vocabulary costs milliseconds. The app therefore keeps the parsed `StyleAnalyser` in `st.session_state` and calls `build_profile` again whenever a control changes, so moving the slider is instant instead of re-running SpaCy.

The cached parse is keyed by the text and the memory budget. Changing either one drops it, so stale results are never shown and the SpaCy document is released rather than held in memory.

## The dual size indicator

Above the copyable block, the app reports the character count and **two token figures,
one per model family.** A single number misleads: Claude Sonnet 5's tokeniser produces
roughly 30% more tokens for the same English text than `cl100k_base`, so a profile
sized to fit a budget on one figure can overflow the other.

The **GPT-family figure** uses `tiktoken`'s `cl100k_base` encoding when that package is
installed, which is exact for the GPT-3.5/GPT-4 family. It is not a dependency, so by
default the figure is an estimate: one token per run of letters, per run of digits and
per non-space symbol. Calibrated against `cl100k_base`, that lands on 99% of the true
count for a generated prompt and within roughly 10% for prose, JSON and source code.
The indicator says `(estimated)` whenever it is not exact.

The **Claude figure is always an estimate**, computed as the GPT figure times 1.3. The
multiplier is named in the caption rather than hidden in the arithmetic, because it has
a shelf life: when an offline Claude tokeniser exists it should replace the multiplier
rather than sit alongside it.

Changing size or format updates both figures without re-parsing.

## Text length and the memory budget
SpaCy's parser and NER models need roughly 1 GB of temporary memory per 100,000 characters, so the memory budget determines how long an input can be. The default is 2 GB (200,000 characters) — deliberately below SpaCy's own 1,000,000-character default, since even that can ask for a lot of memory. Override it with the `COPYME_MEMORY_GB` environment variable or the sidebar control.

If the input is longer than the budget allows, the app reports the length it needs and the budget to raise it to instead of failing inside SpaCy. The same values are returned in the analysis result's `limits` section (`text_length`, `max_length`, `memory_budget_gb`).

## What you get

Five sections, in a fixed order so an API consumer can cache the stable prefix:

1. **Instructions** — write as this person; take the manner and not the subjects; match
   how often each habit occurs rather than merely whether it occurs.
2. **Voice rules** — followable instructions, each with a frequency.
3. **Passages written by this person** — the author's own writing, masked and separated.
4. **Where this usually goes wrong** — up to three predicted drifts. Omitted entirely
   when there is nothing to predict, rather than printed as an empty heading.
5. **Voice card** — up to five lines to re-paste when a long chat starts to drift.

Then a provenance footer naming the copyme version, the profile hash, the sample's word
count and the baseline version. It names no path, host or key.

**The metric dictionary and the raw JSON blocks are gone from the prompt.** They were
sections 1 and 2 of the v1 output, and removing them is the change v2 exists to make: a
model cannot act on `modal_hedging_ratio: 0.04`. Every number is still there for you, in
the collapsed **Raw metrics** section and in the `json` export.

### Export formats

| Target | Shape |
|---|---|
| `first_message` | Markdown, for the first message of a chat |
| `system_prompt` | The same content as standing instructions, with no chat framing |
| `voice_card` | Up to five lines, for re-pasting mid-conversation |
| `sillytavern_card` | Character Card V2 JSON |
| `json` | The whole profile: features, rules with bands, passages with reasons, provenance |
| `exemplars` / `rules` | Either block alone, for an application that assembles its own prompt |

Paste the prose formats into ChatGPT / Claude / any LLM, then ask it to draft on your
behalf.

## A caption worth reading

The app captions the profile whenever the shipped baseline is not fully measured. Rules
are suppressed against that baseline, so the rule set shifts when it is replaced — see
[how-to/refresh-the-baseline.md](how-to/refresh-the-baseline.md).

The baseline currently ships as **measured**, from 391,398 words of real model output,
so no caption appears. The 15 near-zero-frequency features whose spreads have not
converged are recorded in `baseline.json` rather than surfaced in the UI, because the
suppression decision on them is robust for any author who is not sitting exactly on the
threshold.

## Notes
- The app calls `copyme.build_profile(analyser, size=...)` and `copyme.build_pre_prompt`, plus `copyme.score` on the Score tab.
- If Streamlit is not available in your environment yet, run `poetry install` again.
