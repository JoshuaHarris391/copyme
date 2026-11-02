# copyme documentation

Start at the [README](../README.md) to install and run the tool. This folder holds
everything that does not fit on the front door.

| If you want to know | Read |
|---|---|
| What copyme is for and where it is going | [product/](product/) |
| How a change is specified and built | [specs/](specs/) |
| Why the design is the way it is | [adr/](adr/) |
| What each metric means and how it is scored | [linguistic_metrics.md](linguistic_metrics.md) |
| How the Streamlit app behaves | [streamlit_app.md](streamlit_app.md) |
| How to refresh the generic-prose baseline | [how-to/refresh-the-baseline.md](how-to/refresh-the-baseline.md) |
| What has actually been measured about copyme | [evals/](evals/) |

## What is built and what is evidenced

v2's code is **built and tested**: passages and rules replace the metric dictionary in
the prompt, the profile renders to five targets, and a scorer reports what drifted.
`linguistic_metrics.md` and `streamlit_app.md` describe current behaviour, and the
[ledger](work/LEDGER.md) records what landed when.

Built is not the same as evidenced, and two gaps are worth knowing before trusting a
number out of this tool:

- **The generic-prose baseline is measured but not fully converged.** It is sampled
  from 391,398 words of real model output, and every feature driving a substantive rule
  has settled; 15 near-zero-frequency spreads (emoji, exclamations, ellipses,
  semicolons) have not, and are named per feature in `baseline.json`. See
  [how-to/refresh-the-baseline.md](how-to/refresh-the-baseline.md).
- **The blind evaluation has not been run**, because it needs three or more human
  readers per author. Several shipped parameters are therefore intuitions with defaults
  attached. See [evals/](evals/).

`product/` describes intent rather than behaviour; where the two have diverged, the
[spec deviations table](specs/README.md) records it.

## Owner

Single maintainer: the repository owner. Nothing here runs as a service, so there is no
on-call rotation and no incident runbook. The one recurring maintenance job is
[how-to/refresh-the-baseline.md](how-to/refresh-the-baseline.md).
