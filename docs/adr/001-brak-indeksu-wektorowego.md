# 001 — No vector index on embeddings

**Status:** accepted for now; since 4 September 2026 the threshold is watched by an alert
**Date:** 4 September 2026
**Revised:** 4 September 2026, after measuring on the production instance

## Decision

`documents_documentchunk.embedding` carries no index. Retrieval computes an L2
distance for every chunk belonging to that tenant and sorts the result.

## What it costs

Measured on the **production instance**
([docs/skala-i-wydajnosc.md](../skala-i-wydajnosc.md)):

| chunks | median |
|---|---|
| 1 000 | 90 ms |
| 5 000 | 396 ms |
| 10 000 | 1 297 ms |

Worse than linear, with the knee between 5 000 and 10 000.

Against the plan limits, conservatively: Start full is at least 0.7 s of
retrieval, Grow at least 3.3 s, Pro at least 13 s.

## What was rejected

**An HNSW index.** pgvector supports it and it would flatten the curve. It was
not added because it makes retrieval *approximate*: recall drops below 100%,
and by how much is precisely what `rag/test_ocena.py` measures. Adding it
without re-running that evaluation would be trading a latency number for an
answer-quality number while looking at only one of them.

That is not an argument against the index. It is an argument against adding it
blind. The evaluation harness exists; whoever adds the index should run it
before and after and put both sets of numbers in the scale document.

**Lowering the plan limits** to what is served quickly. Still on the table, and
cheaper than it sounds — see below.

## Why this is still acceptable today

The largest real knowledge base is 246 chunks — about 22 ms on production. No
customer is anywhere near trouble, and adding an approximate index to solve a
problem nobody has would trade measurable answer quality for latency nobody is
waiting on.

## Revised

The first version of this record used numbers from a development laptop and set
the revisit threshold at 10 000 chunks. Measured on the production instance,
the same query is 13× slower at a thousand chunks and **32× slower at ten
thousand** — the ratio grows, so a laptop is not a slower server, it is a
different shape that hides the knee entirely.

Two things follow.

**The threshold is wrong.** The knee is between 5 000 and 10 000 chunks on real
hardware, and the Start plan's own limit (~5 140 chunks) already sits at it.
Watch for **2 500 chunks**, half the knee, not ten thousand.

**The decision is closer than it looked.** This record still says "not yet",
but the reason has changed: it is no longer "the ceiling is two orders of
magnitude away", it is "the ceiling is one order of magnitude away and no
customer has walked toward it". Those need different amounts of attention.

## What should make somebody revisit this

Any one of these:

- a tenant passes **2 500 chunks** — half the measured knee, so there is time
  to act,
- a Grow or Pro plan is sold to somebody who intends to use its full allowance,
  which today the system cannot serve,
- retrieval latency appears in a customer complaint.

The first is now watched rather than waited for: a daily task
(`accounts/rozmiar_bazy.py`) reports any tenant crossing 2 500 chunks, and
again at 5 000 — the knee itself, which is also the Start plan's own limit.
Two levels rather than one, because a single threshold answers "has it
happened" and two also answer "how much time is left".

The alert goes to the operator, not the customer. A customer cannot act on it:
they do not know what a chunk is, and the only lever they have — deleting their
own knowledge — is the opposite of what they bought the product for. The
decision between an index, different plan limits and a conversation about the
plan belongs on our side.

## What changed on 7 September 2026

The production query plan settled the question this record left open. At 10 000
chunks the query reads **10 107 blocks — about 79 MB — from disk**, essentially
the whole table, on every question. It is a memory effect, not a processor one.

Two consequences for this decision.

**There was a cheaper lever than the index, and it was taken.** Asking the
embedding model for 512 dimensions instead of 1536 keeps recall and silence
unchanged (90.9% and 75.0%, with the threshold moved from 1.00 to 0.96) and
makes the table 2.9× smaller: 27 MB instead of 80 at ten thousand chunks. If
the cache sits between those numbers, the disk reads disappear. Unlike the
index, this keeps search exact. Shipped the same day; runbook in
[docs/zmiana-wymiaru-wektora.md](../zmiana-wymiaru-wektora.md).

**The index is now third in line, not second.** Remaining order: `halfvec`
(pgvector 0.8 is installed), then a larger database instance, then the
index — because only the last one trades away answer quality.

**This record's decision still stands, and is now less pressing.** No index,
for the same reason as before: nobody is near the ceiling, and the ceiling
just moved further away. What has not been redone is the production
measurement at 512 dimensions, so how much further is unknown.

Numbers in [docs/skala-i-wydajnosc.md](../skala-i-wydajnosc.md).

## How to add the index, when it comes to that

Run `rag/test_ocena.py` before and after and put both sets of numbers in the
scale document. The evaluation harness exists precisely so that this decision
is made on two numbers instead of one.
