# copyme documentation

Start at the [README](../README.md) to install and run the tool. This folder holds
everything that does not fit on the front door.

| If you want to know | Read |
|---|---|
| What copyme is for and where v2 is going | [product/](product/) |
| How a v2 change is specified and built | [specs/](specs/) |
| Why the design is the way it is | [adr/](adr/) |
| What each metric means and how it is scored | [linguistic_metrics.md](linguistic_metrics.md) |
| How the Streamlit app behaves today | [streamlit_app.md](streamlit_app.md) |

## What is built and what is designed

`linguistic_metrics.md` and `streamlit_app.md` describe copyme **as it ships today**
(v1.0.0): the sample is measured, the measurements are pasted into a pre-prompt, and
the sample itself is discarded.

`product/` and `specs/` describe **v2**, which is designed but not built. Nothing in
those two folders is a statement about current behaviour. Each spec says which files
it creates or changes, and the [ledger](work/LEDGER.md) says how far the work has got.

## Owner

Single maintainer: the repository owner. There is no on-call rotation and nothing in
this project runs as a service, so there is no runbook.
