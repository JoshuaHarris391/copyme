# copyme product documentation

copyme v2 stops sending a language model a statistical description of someone's
writing and starts sending the writing itself, chosen well, with the statistics
turned into rules the model can follow.

That one sentence is the whole change. Everything in this folder follows from it.

| Document | Answers |
|---|---|
| [vision.md](vision.md) | What copyme is for, what is wrong with v1, and what replaces it |
| [user-journey.md](user-journey.md) | What a user does, step by step, and what they get back |
| [success-and-evaluation.md](success-and-evaluation.md) | How we will know v2 worked, and the release gate |
| [non-goals.md](non-goals.md) | What copyme will not do, including where it stops on copyright and voice cloning |
| [roadmap.md](roadmap.md) | Four milestones, what each ships alone, and the gate on each |
| [integrations.md](integrations.md) | Using a profile in Maya, SillyTavern, Claude Projects, or any system prompt |
| [research.md](research.md) | The published work the design rests on |

## The source

This folder is a restatement of a single design document, written as the product half
of a spec review on 2026-11-01. The engineering half is in [../specs/](../specs/) and
the decisions it locks in are in [../adr/](../adr/).

Where this folder and the source document disagree, the disagreement is recorded as a
deviation in [../specs/README.md](../specs/README.md) rather than silently resolved.

## Status

Designed, not built. copyme v1.0.0 is what is installed when you `poetry install`
today; see [../README.md](../README.md) for what it currently does.
