# 0003 — Filter vocabulary to manner words and mask one-off names

**Status:** Accepted, 2026-11-01. Implemented by
[spec 02](../specs/02-separation-and-exports.md).

## Context

Sending real passages ([ADR 0001](0001-exemplars-over-descriptions.md)) brings the
sample's subject along with its manner. Two places leak.

**The vocabulary block.** v1 lists the author's most frequent words and phrases. On any
real sample that list is mostly the sample's subject. A profile built from someone's
work email yields a model that keeps mentioning the quarterly report.

**The exemplars themselves.** They contain names — colleagues, clients, places. A name
that appears once in a 20,000-word sample is incidental to the voice, but once it is in
the prompt the model will use it.

This matters most for the use copyme is most wanted for: a character voice in an
assistant, where the character's circumstances must not come along.

## Decision

Three filters, all computed on the existing parse.

**Keep function and manner words; drop content words.** From the frequency ranking,
keep conjunctions, adpositions, determiners, pronouns, particles, adverbs and
interjections, plus a short allow-list of intensifiers and hedges. Drop nouns, proper
nouns and most verbs. What survives is the author's connectives and qualifiers — what
stylometry has always found diagnostic.

**Keep idioms; drop topical phrases.** A repeated 2-to-4-word phrase survives only if
it contains no noun that is also in the sample's top-50 content nouns, and no named
entity. "The thing is", "I mean", "which is to say" survive; "the quarterly report"
does not.

**Mask names below a threshold.** Named entities in exemplars become role placeholders
— `[a colleague]`, `[a city]` — when the entity appears **fewer than three times** in
the sample. Recurring names are kept.

The instruction block states the separation outright: *the examples show how this
person writes, not what they know or believe; do not import their subjects, names,
settings or opinions.*

## Alternatives considered

**Mask every named entity.** Rejected. StyleTunedLM (Liu, Diddee and Ippolito, INLG
2024) found masking names costs nothing for style learning, which makes masking safe —
but an author's *recurring* references are part of their voice. A writer who mentions
the same three people constantly writes differently from one who never names anyone.
Masking everything would flatten that.

**Mask nothing and rely on the instruction.** Rejected. The instruction is necessary
and not sufficient: a one-off name sitting in an exemplar is an invitation, and the
failure mode — a generated draft naming a real person who has nothing to do with it —
is exactly the kind that makes the tool unusable at work.

**Drop the vocabulary block entirely.** Considered seriously, since the exemplars
already contain the author's connectives in context. Rejected because the explicit list
is cheap, is the one part of v1's word data with evidence behind it, and gives the
scorer something to compare against.

**Use a stop-word list instead of POS tags.** Rejected: the spaCy parse is already in
hand, so POS filtering is free and far more accurate than a fixed list, especially for
the adverbs and interjections that carry the most voice.

## Consequences

**Good**

- A profile of a topical sample produces a model that writes in that voice about
  anything.
- The same mechanism makes a profile safe to share: it carries manner, not the
  colleagues named in the source.
- The filters are pure functions of the existing parse, so they cost no extra parsing
  and respond instantly to the sliders like everything else downstream.

**Costly**

- Dialogue-heavy samples may lose a lot to masking, because dialogue names people
  constantly. The threshold is a parameter and the question is open — see
  [spec 02](../specs/02-separation-and-exports.md).
- Three filters are three more things that can be wrong, and a wrongly dropped manner
  word is invisible: it just quietly does not appear.
- Masking changes the exemplar text, so a user comparing an exemplar against their
  source sees placeholders. The reason line and `mask_names=False` both exist for this.

**What this does not do**

Masking is not anonymisation and is not a provenance tool. It stops a one-off name
leaking into generated text. It does not make a profile of in-copyright text safe to
publish, and copyme ships no feature that strips a sample of its attribution — see
[../product/non-goals.md](../product/non-goals.md).
