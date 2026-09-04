# 001 — No vector index on embeddings

**Status:** accepted, with a threshold that should trigger a revisit
**Date:** 4 September 2026

## Decision

`documents_documentchunk.embedding` carries no index. Retrieval computes an L2
distance for every chunk belonging to that tenant and sorts the result.

## What it costs

Measured, not estimated ([docs/skala-i-wydajnosc.md](../skala-i-wydajnosc.md)):

| chunks | median |
|---|---|
| 1 000 | 7 ms |
| 10 000 | 40 ms |
| 40 000 | 422 ms |
| 85 000 | 818 ms |

Roughly linear to ten thousand, worse after. The Pro plan sells 100 MB of
knowledge base — about a hundred thousand chunks — so a customer who fills that
plan waits around a second before the model writes anything.

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

## Why this is acceptable today

The largest real knowledge base is 246 chunks: 0.24% of the Pro limit, about
3 ms. No customer is within two orders of magnitude of the problem.

Adding an index now would mean accepting a measurable quality cost to solve a
problem nobody has, and doing it at the moment when there is the least real
data to validate the trade-off against.

## What should make somebody revisit this

Any one of these:

- a tenant passes **10 000 chunks** — the point where the curve stops being
  linear,
- retrieval latency shows up in a customer complaint,
- a Pro plan is sold to somebody who intends to use its full allowance.

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
