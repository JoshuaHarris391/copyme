# Linguistic Style Metrics: Specifications, Methods & Interpretations

| Metric | Description | Assessment Categories (Thresholds) | Calculation Method | Interpretation of Categories |
| :--- | :--- | :--- | :--- | :--- |
| **Type-Token Ratio (TTR)** | Measures lexical diversity (uniqueness of vocabulary). | **> 0.60**: "diverse"<br>**> 0.40**: "standard"<br>**≤ 0.40**: "repetitive" | `len(unique_words) / word_count` | **Diverse:** High vocabulary richness; precise descriptions; avoids repeating words.<br>**Standard:** Typical balance of new vocabulary and repeated function words.<br>**Repetitive:** Limited vocabulary; relies heavily on same words; common in simple primers or redundant speech. |
| **Mean Length of Sentence (MLS)** | Average sentence length; indicates syntactic complexity. | **> 25**: "complex/elaborate"<br>**> 15**: "standard"<br>**≤ 15**: "short/telegraphic" | `word_count / sentence_count` | **Complex:** Academic/formal style; uses multiple clauses and detailed qualifiers.<br>**Standard:** Balanced flow suitable for general readers or journalism.<br>**Short:** Punchy, direct, or fragmented style; typical of dialogue or action scenes. |
| **Punctuation Density** | Frequency of punctuation marks per 1,000 words. | **> 150**: "heavily punctuated"<br>**> 100**: "balanced"<br>**≤ 100**: "sparse" | `(punct_count / word_count) * 1000` | **Heavily Punctuated:** Complex structure with many pauses, lists, or clauses (commas, semicolons).<br>**Balanced:** Standard grammatical pacing.<br>**Sparse:** Long, flowing run-on sentences or simple "subject-verb-object" structures with few breaks. |
| **Discourse Marker Density** | Frequency of fillers (e.g., "like", "well"). | **> 40**: "conversational"<br>**> 15**: "natural"<br>**≤ 15**: "formal/polished" | `(count(markers) / word_count) * 1000` | **Conversational:** Spoken-style spontaneity; "thinking out loud"; high informality.<br>**Natural:** Relaxed writing that mimics speech without excess clutter.<br>**Formal:** Edited, scripted, or academic text; strictly avoids fillers. |
| **Hapax Legomena Ratio** | Ratio of words appearing exactly once (uniqueness). | **> 0.60**: "unique/creative"<br>**> 0.40**: "rich"<br>**≤ 0.40**: "basic/repetitive" | `count(freq==1) / len(unique_words)` | **Unique:** Highly descriptive or literary; constantly introduces new concepts/terms.<br>**Rich:** Good variety; engaging but grounded.<br>**Basic:** Relies on a small core set of "anchor" words; predictable. |
| **Formulaic Density** | Reliance on repeated phrases/n-grams. | **> 0.30**: "highly formulaic"<br>**> 0.10**: "standard"<br>**≤ 0.10**: "original" | `sum(repeated_counts) / word_count` | **Highly Formulaic:** Relies on clichés, idioms, or repetitive rhetoric (e.g., political speeches).<br>**Standard:** Uses common collocations (e.g., "in the end").<br>**Original:** Novel phrasing; avoids stock phrases or predictable patterns. |
| **Modal Hedging Ratio** | Frequency of uncertainty markers (e.g., "could"). | **> 0.20**: "tentative/hedged"<br>**> 0.05**: "balanced"<br>**≤ 0.05**: "assertive/direct" | `count(hedges) / sentence_count` | **Tentative:** Cautious, scientific, or polite; avoids absolute claims.<br>**Balanced:** Mixes facts with appropriate caution.<br>**Assertive:** Authoritative, factual, or commanding; expresses high certainty. |
| **Flesch Reading Ease** | Standard readability score (0–100 scale). | **> 80**: "very easy"<br>**> 60**: "easy/standard"<br>**> 40**: "difficult"<br>**≤ 40**: "technical" | `textstat.flesch_reading_ease` | **Very Easy:** 5th-grade level; simple words/sentences (children's books).<br>**Easy:** Conversational/Standard English.<br>**Difficult:** Intellectual/College level.<br>**Technical:** Academic papers or legal contracts; requires specialized knowledge. |
## Where these metrics are used now

All nine remain computed and all nine remain available — in the app's collapsed **Raw
metrics** section and in the `json` export. What changed in v2 is that **none of them
is prompt content any more.** A model cannot act on `modal_hedging_ratio: 0.04`, so the
prompt carries the author's passages and a set of followable rules instead, and these
numbers work behind it.

Two have narrower roles than the rest:

| Metric | Role |
|---|---|
| **Formulaic Density** | Still pinned to 2–4 word sequences, so two profiles stay comparable whatever the phrase slider is set to. Its *phrases* feed the signature-idiom list, but only after the style/content filter. |
| **Cohesive Harmony** | Kept as a descriptor and **produces no rule.** The research gave no evidence that a model can act on it. |
| **Function Word Frequency** | **Profile-only.** It is an authorship-attribution feature with no generation value, and it left the prompt entirely. |

## The v2 feature set

These are the features that select passages, phrase rules and score drafts. Every one
is a rate or a distribution rather than a raw count, so a 2,000-word sample and a
200,000-word one are directly comparable — which is what makes all three of those jobs
possible. They are computed for the whole document and for each candidate passage.

Defined in [`src/copyme/features.py`](../src/copyme/features.py); the canonical order is
`FEATURE_NAMES`.

| Feature group | Scalars | The rule it produces |
|---|---|---|
| **Sentence length** | `sentence_length_q1`, `_median`, `_q3`, `_p90`, `_cv`, `share_short_sentences`, `share_long_sentences` | *"Keep most sentences between 10 and 26 words… one in ten runs past 35. Do not even the lengths out: the spread is the rhythm."* Reported as a distribution precisely because a flat mean produces the uniform rhythm readers identify as machine-written |
| **Sentence openers** | `opener_conjunction_rate`, `opener_pronoun_rate`, `opener_adverb_rate`, `opener_concentration` | *"Open one in five sentences with a conjunction — And, But, So."* The literal top ten openers are kept in the feature detail |
| **Contractions** | `contraction_rate` | *"Always contract"*, *"Never contract"*, or a rate. Divided by the opportunities to contract, not by the word count, so "never contracts" and "had nothing to contract" are different findings |
| **Person and address** | `first_person_singular_per_1k`, `first_person_plural_per_1k`, `second_person_per_1k` | *"Address the reader directly as you, about once a paragraph."* |
| **Questions and exclamations** | `question_rate_per_1k`, `exclamation_rate_per_1k` | *"Ask a question roughly every 200 words; never exclaim."* |
| **Punctuation habits** | `em_dash_per_1k`, `ellipsis_per_1k`, `parenthetical_per_1k`, `semicolon_per_1k`, `colon_per_1k`, `comma_per_sentence` | *"Use an em dash about once a paragraph. No parentheses."* The dash *form* in use is recorded, so the rule names the right one |
| **Fragments** | `fragment_rate` | *"Let one sentence in eight be a fragment — no finite verb, used for emphasis."* |
| **Paragraph shape** | `paragraph_sentences_median`, `paragraph_sentences_q3`, `opening_sentence_length`, `closing_sentence_length` | *"Paragraphs of about three sentences, rarely more than five. End on a short line; do not close with a summarising sentence."* |
| **Case and emoji** | `lowercase_start_rate`, `allcaps_per_1k`, `emoji_per_1k` | Mostly relevant to chat and social samples. Only stated when it is a real habit rather than a stray token |
| **Vocabulary range** | `mattr` | *"Repeat words rather than reaching for synonyms."* |
| **Register** | `discourse_marker_per_1k`, `modal_per_1k`, `hedge_per_1k` | *"Write conversational: about 54 discourse markers per 1,000 words, roughly one a sentence."* Grounded rather than a bare adjective, which is the part the research found weak |
| **Subject density** | `named_entity_per_1k` | **No rule.** It describes what the sample is *about*, and the prompt explicitly tells the model not to import the author's subjects. It is used to skip passages that would drag a topic along |

### Why MATTR and not type-token ratio

Raw TTR falls as a text grows — it is unique words over total words, and the
denominator grows faster — so it cannot compare a short sample with a long one, which
is exactly what copyme does throughout.

The replacement was chosen by measurement, not preference. Across a 2,000-word and a
20,000-word slice of the same golden author:

| Measure | Worst drift | Shipped |
|---|---|---|
| **MATTR** (moving-average TTR, 100-word windows) | **5.7%** | Yes |
| MTLD (measure of textual lexical diversity) | 36.9% | No |
| Raw type-token ratio | 61.0% | No, retained as a v1 metric only |

The spec set a 10% bar; only MATTR clears it. `mtld()` remains in the codebase so the
comparison can be re-run rather than taken on trust, and the test that chose it is in
`tests/test_features.py`.

### Rule suppression

A feature within **half a standard deviation** of the generic-prose baseline produces no
rule at all: the model's default is already right, and every extra line dilutes the ones
that matter. The baseline is currently **provisional**, which makes suppression
conservative — see
[how-to/refresh-the-baseline.md](how-to/refresh-the-baseline.md).
