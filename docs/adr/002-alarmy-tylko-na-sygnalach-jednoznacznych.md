# 002 — Alert only on unambiguous signals

**Status:** accepted
**Date:** 4 September 2026

## Decision

An alert fires only where the condition it reports is not open to
interpretation. Concretely:

- **refusals** (`accounts/odmowy.py`) — a widget that refuses service is
  refusing; there is no quieter reading of it,
- **silence** (`accounts/cisza.py`) — zero conversations for three days, and
  only for a tenant that had traffic on at least 18 of the preceding 21 days,
- **subscription dates** (`accounts/tasks_konce.py`) — a date has passed or it
  has not.

Nothing fires on a trend, a percentage change, or a threshold that needs a
judgement call to interpret.

## What it costs

Real degradation goes unnoticed. A tenant falling from 200 conversations a day
to ten is a business problem — possibly a bigger one than a tenant going to
zero, because it is likelier to be a slow content or quality failure than a
snippet that fell off a page. Nothing here catches it.

## What was rejected

**Alerting on a percentage drop in traffic.** It needs assumptions about the
distribution of a tenant's traffic, and every assumption is wrong for some
tenant. A quiet week, a public holiday, an out-of-season month all look like
the same signal.

The reason this matters more than it sounds: the incident this whole line of
work came from
([docs/incydent-2026-08-26.md](../incydent-2026-08-26.md)) was a failure that
lasted a day because nobody was told. The fix is a system of alerts that get
read. An alert that fires on every quiet week is not read after the third one,
and then the alert that matters is not read either.

So the trade is: we accept a blind spot in exchange for every alert that does
fire meaning something. A quieter system with a known gap beats a noisier one
with an unknown one.

## Where the blind spot is covered instead

Partially, and by different means:

- weekly digest of unanswered questions — a content failure shows up there as
  questions the bot could not handle,
- retrieval quality has floors in CI, so a regression in answers fails the
  build rather than waiting to be noticed in production,
- the panel's *System health* screen shows background jobs and knowledge base
  state on demand.

None of these is an alert. Somebody has to look. That is the honest position.

## What should make somebody revisit this

When there are enough tenants that a per-tenant baseline is statistically
meaningful — roughly, when losing one customer to a slow decline would cost
more than the noise of a trend alert costs in attention. Below about a dozen
active tenants that maths does not work.
