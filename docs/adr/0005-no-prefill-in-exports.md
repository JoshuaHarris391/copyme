# 0005 — No export emits assistant-message prefill

**Status:** Accepted, 2026-11-01. Implemented by
[spec 02](../specs/02-separation-and-exports.md).

## Context

A common technique for locking a model into a register is **prefill**: start the
assistant's turn with the opening words of the desired reply, so the model continues in
that voice rather than choosing its own opening. Older SillyTavern presets lean on it
heavily, and it is genuinely effective where it is available.

Claude Sonnet 4.6 and later **reject prefill with a 400 error**.

copyme's most-wanted export is a SillyTavern Character Card V2, and its most-wanted
target model is Claude. An export that carried prefill would fail outright on the
combination the tool is most likely to be used in — and fail at request time, in
someone else's application, with an error that does not mention copyme.

## Decision

No copyme export emits prefill, and no export emits an assistant-role message of any
kind.

Where a register-locking opening is wanted, **the in-voice opening line goes inside the
system text** as part of the instruction block.

This is checked, not merely intended: an acceptance criterion asserts that no export
contains an assistant-role message.

## Alternatives considered

**Emit prefill only for non-Claude targets.** Rejected. The target model is a property
of the application the card is dropped into, not of the card, and the user can change
it after export. A card that works until someone switches model is worse than one that
never used the technique, because the failure surfaces far from its cause.

**Emit prefill and document the restriction.** Rejected for the same reason. The person
hitting the 400 error is often not the person who exported the card.

**Make prefill an opt-in flag.** Rejected as a feature nobody can safely choose: it
requires knowing which model a downstream application will use at request time, which
is exactly the thing the exporter does not know.

## Consequences

**Good**

- Every export works on Claude Sonnet 4.6 and later, which is the main target.
- One less field to map, validate and keep aligned with a moving provider constraint.
- Register locking still happens, through system text that is portable across every
  provider.

**Costly**

- On models that do accept prefill, copyme gives up a technique that would have helped.
  The instruction-block opening line is a weaker substitute.
- SillyTavern users migrating from a prefill-based preset may find the register less
  tightly held at the start of a conversation. The voice card at Author's Note depth 4
  is the compensating mechanism.

**Revisit when**

Provider support changes. If prefill becomes available again on the target models, this
ADR is superseded rather than edited — and the replacement has to answer the
"exporter does not know the target model" objection, which is the real reason for the
decision rather than the 400 error itself.
