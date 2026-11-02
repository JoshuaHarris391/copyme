# The evidence base

Every design decision in v2 traces to one of these. They were reviewed in the
conversation that produced the source design document on 2026-11-01; the summaries
below are that review's findings, not independent verification by this repository.

| Work | Finding | What it decides in copyme |
|---|---|---|
| Chakrabarty, Ginsburg and Dhillon, arXiv 2510.13939v4 (2026) | Expert readers rejected in-context imitation (OR 0.16) and preferred fine-tuned imitation (OR 8.16); cliché density explained part of the penalty | The success bar is "recognisable", not "undetectable"; the static known-failure notes name cliché habits explicitly |
| Cho et al., TICL, arXiv 2502.08972 (2025) | Trial-error-explain prompting on Claude 3 Sonnet; explicit style analysis underperformed plain few-shot; OPRO scored 0% against real authors; prompts did not transfer across models | The contrastive block exists, and the explanation carries the gain; the live tier records which model it ran against |
| Kim and Jurgens, arXiv 2606.05716 (2026) | LLM-written style descriptions were worse than random at recovering a style embedding | Descriptions are not the prompt |
| Patel, Andrews and Callison-Burch, STYLL, AAAI 2024 | Descriptor plus paraphrase pairs; "towards target" never above 0.16 | Descriptor-only prompting is not enough on its own |
| Wang et al., EMNLP 2025 Findings | Few-shot helps; informal voices remain hard | Exemplars are the core; informal samples get the lowest expectations |
| Liu, Diddee and Ippolito, StyleTunedLM, INLG 2024 | Masking names cost nothing for style learning; roughly 50k tokens needed for stable author style when fine-tuning | Name masking is safe to apply; the 2,000-word floor and 10,000-word recommendation |
| Li et al., COLM 2024 | Instruction and persona drift within eight turns; repetition and re-injection help | The voice card, and the drift check at turns 1, 8, 16 and 20 |
| Agarwal et al., NeurIPS 2024 | Many-shot in-context learning overrides pretraining biases | The Full preset at 20 to 30 exemplars is worth building, not just the Compact one |
| StyleDistance (NAACL 2025) and the Wegmann style embeddings | Content-independent style similarity, small enough for CPU | The optional `copyme[embeddings]` scorer extra |

## How the evidence is used, and where it stops

The evidence supports the **shape** of v2: exemplars over descriptions, rules stated as
behaviour, a contrastive block with explanations, re-anchoring against drift, and a
success bar below "undetectable".

It does not support the **numbers** v2 picks: the 0.4 / 0.4 / 0.2 selection weights,
the 120-to-400-token passage window, the half-standard-deviation rule-suppression
threshold, the three-occurrence name-masking threshold. Those are starting points,
exposed as parameters, to be decided by the golden-sample tests in milestone 4 rather
than by intuition. They are listed as open questions in each spec.

A standing caution from the same review: LLM-judge scores may be collected but do not
gate a release, because judges favour model text.
