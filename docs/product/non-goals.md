# What copyme will not do

Each of these is a decision, not an omission. They bound the work and they bound the
claims made for it.

## Fool an expert

The strongest human study reviewed found that only fine-tuning on an author's complete
works convinced trained readers; in-context imitation was actively rejected.

copyme is a prompting tool. It aims for a voice a friend would recognise, not one a
scholar would. The published target is a 70% blind pick rate, which is a long way from
undetectable and is deliberately stated that way. See
[success-and-evaluation.md](success-and-evaluation.md).

## Capture a voice from a paragraph

Below about 2,000 words there is not enough text to choose exemplars from, and the
rules rest on too few sentences. The app says so rather than producing a confident
profile from thin evidence.

This is a visible behaviour, not a silent degradation: the UI names the word count it
has and what it would need.

## Reproduce the sample

Exemplars are shown to the model as evidence of *manner*, with an explicit instruction
not to reuse their sentences, names or subjects. The copying check in the scorer
enforces it: any run of 12 or more consecutive words shared with the sample is flagged.

## Clone a real person's speaking voice

copyme works on text. Pairing it with a cloned *speaking* voice of a named real person
— an actor, a public figure — is out of scope, and after the 2024 "Sky" dispute it is
legally live. Where a project needs a spoken register, use a voice that evokes the
register rather than one that imitates a person.

## Decide copyright for the user

Profiling a published author's text for personal use and publishing a model that
imitates them are different positions, in law and in ethics. copyme does not pretend to
resolve that.

What the tool does instead:

- The README says plainly that the two cases differ and that the user owns the call.
- Every export carries a provenance footer naming the sample's size and the profile
  hash, so a profile can be traced back.
- **No feature strips a sample of its attribution.** There will be no "anonymise this
  source" affordance.

Name masking inside exemplars exists to stop a one-off name leaking into generated
text, not to launder provenance; recurring names are kept, because the author's
recurring world is part of the voice.

## Identify the author

Nothing in the JSON profile identifies the author beyond what the user typed into a
name field. A program consuming a profile gets manner, not identity. See
[integrations.md](integrations.md).
