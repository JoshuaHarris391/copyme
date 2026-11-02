# Using a profile in other applications

The JSON profile is the contract. Every other integration is a renderer over it.

```
Profile (json)
  ├── first_message       → a chat
  ├── system_prompt       → Claude Projects, custom GPTs, any system field
  ├── voice_card          → re-pasted mid-conversation, or a per-turn reminder
  ├── sillytavern_card    → SillyTavern and any Character Card V2 front end
  ├── exemplars / rules   → an application's own prompt assembly (Maya below)
  └── score()             → whatever evaluation the application already has
```

The general pattern, which covers every application not named below:

- **Exemplars and rules go in the stable, cacheable part** of the prompt.
- **The voice card is appended to the per-turn part**, because prompted voices decay
  after about eight turns and the card is the anti-drift mechanism.
- **`score()` is wired into the application's existing evaluation**, so a voice
  regression shows up where other regressions already do.

Where an application has a retrieval step, each JSON exemplar carries a short
`situation` tag, so the application can pick the five most relevant for the current
turn instead of sending all thirty.

## SillyTavern

```bash
copyme card profile.json --out author.png
```

Writes a Character Card V2 PNG with the JSON embedded, which SillyTavern imports by
drag and drop.

| Card field | Filled from |
|---|---|
| `description` | The voice rules |
| `mes_example` | The exemplars, in SillyTavern's `<START>` dialogue format |
| `system_prompt` | The instruction block |
| `creator_notes` | The voice card, with a note to paste it into the Author's Note field at depth 4 |

Author's Note at depth 4 is SillyTavern's own anti-drift mechanism, which is why the
voice card is routed there rather than buried in the description.

**No prefill is emitted.** Older SillyTavern presets lean on assistant-message prefill
to lock register, and Claude Sonnet 4.6 and later reject prefill with a 400 error. The
in-voice opening line goes inside the system text instead. See
[../adr/0005-no-prefill-in-exports.md](../adr/0005-no-prefill-in-exports.md).

## Claude Projects and custom GPTs

Render `format="system_prompt"` at Full size and paste it into the project instructions
once. The project then holds the voice for every chat without re-pasting.

The voice card is still worth re-pasting in long chats, and the export footer says so.

## Maya

Maya is the worked example of the general pattern. It already has the prompt-side
machinery — `persona/voice.py`, `head.md` with its cache breakpoint, the voice gate,
the eval judge. What it lacks is exemplars and a per-turn anchor, and both come from a
copyme JSON profile.

The flow: write the source lines, profile them with copyme, drop two generated files
into `~/.maya/persona/`, and add two placeholders to `head.md`.

**Source.** For a character voice, the input to copyme is a hand-written set of 40 to
80 lines *in that manner*, placed in Maya's own situations (the bank call, the flat
"yeah", the task moved four times) — not screenplay text. copyme then does what it is
good at: picks the most characteristic lines, writes the observable rules, and produces
the voice card. A character's screen dialogue is far below the volume any fine-tune
would need, so prompting is the right route regardless.

**Files.**

| File | copyme format | Goes to |
|---|---|---|
| `~/.maya/persona/exemplars.md` | `exemplars` | `{exemplars}` in `head.md` section 1, above the cache breakpoint |
| `~/.maya/persona/voice_rules.md` | `rules` | Appended after the existing `voice.md` in `voice_prompt()` |
| the voice card (five lines) | `voice_card` | `{voice_card}` at the end of `head.md` section 5, below the breakpoint |

**Code changes in Maya**, each its own spec in that repository:

1. `voice.py`: read `exemplars.md` with its own cap (6,000 tokens, not the
   4,000-character limit on `voice.md`); expose `exemplars_text(home)` and add
   `voice_card_text(home)`.
2. `head.md`: add `## How you sound: examples` with `{exemplars}` to section 1; add
   `{voice_card}` as the last lines of section 5. The first is cached for the day; the
   second costs a few dozen uncached tokens per turn and is the anti-drift mechanism,
   since the thread window runs to 40 turns before summary and prompted voices decay
   by about eight.
3. `evals/judge.py`: add an `off_voice` class beside `invented_time` and
   `invented_title`, with the rubric generated from the rules file. A failing reply
   plus the judge's one-line reason is exactly a copyme known-failure note.
4. Later: a `maya persona harvest` command collecting gate rejections and `off_voice`
   verdicts into `known_failures.md`, which `head.md` includes below the exemplars.
   This is the live contrastive tier, run against the model Maya actually uses — which
   the research says is the only model it will work on.

**Fit with Maya's existing rules.** The `_HOW_A_FRIEND_WRITES` block already asks for
contractions, thinking aloud and short lines, so it stays. Traits that collide with
Maya's 320-character beat limit should be excluded from the source lines, not left for
the prompt to fight. `score()` gives the eval runner a per-reply voice number for the
scripted scenarios in Maya's own testing docs.

## As a library

```python
from copyme import Profile, score
```

Enough for a program that only wants to check voice. The embeddings extra is the one
dependency that pulls a model, and it is opt-in.

## What a consumer does not get

Nothing in the JSON identifies the author beyond what the user typed into a name field,
and exemplars carry name masking as configured. A program consuming the profile gets
manner, not identity.
