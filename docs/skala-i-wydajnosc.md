# How far this scales, measured

**Measured:** 4 September 2026, local PostgreSQL 16 with pgvector.
**Repeat it yourself:** `python manage.py zmierz_skale`

The question this answers: **how many customers, and how large, before the bot
gets slow?** Until this measurement there was no answer and no way to get one.

---

## What was measured, and what was not

Not throughput in requests per second. That depends on the machine, and a
number from a development laptop says nothing about a Render instance — it
would look like a result without being one.

What was measured is the **shape**: how retrieval time grows with the number
of chunks. That is a property of the query and of the absence of a vector
index, not of the processor. Run on the server the absolute numbers will
differ; the shape will not.

---

## The numbers

| chunks | median | worst |
|---|---|---|
| 1 000 | 7 ms | 10 ms |
| 5 000 | 22 ms | 23 ms |
| 10 000 | 40 ms | 43 ms |
| 40 000 | 422 ms | 517 ms |
| 85 000 | 818 ms | — |

Roughly linear to 10 000, then worse than linear. The query plan explains it:
a sequential scan over the tenant's chunks, computing an L2 distance for each,
then a sort. There is **no vector index** on the embedding column — only the
primary key and the foreign key to the document.

---

## Where this meets the price list

A chunk holds at most 1200 characters and overlaps its neighbour by 180, so
each one advances about 1020 characters of source text.

| plan | knowledge base | chunks | retrieval |
|---|---|---|---|
| start | 5 MB | ~5 100 | ~20 ms |
| grow | 25 MB | ~25 700 | ~250 ms |
| pro | 100 MB | ~102 800 | **~1 s** |

**A customer who fills a Pro plan waits about a second for retrieval alone**,
before the model has written a single word. The answer streams, so that second
is spent staring at nothing.

For scale: the largest real knowledge base today is 246 chunks — 0.24% of the
Pro limit, about 3 ms. Nobody is anywhere near this ceiling. It is written down
so that the first customer who approaches it is not a surprise.

---

## A wrong conclusion, corrected

The first measurement showed `Seq Scan on documents_documentchunk` over
**every** row in the table, with the tenant filter applied afterwards by a hash
join. Read alone, that says one customer's data slows down every other
customer's chatbot — compounding, and serious.

It is not true, and the reason is mundane: in that first run all 40 000 chunks
belonged to a single tenant, so scanning them all *was* scanning that tenant.

Checked directly, with two tenants in one database:

| | |
|---|---|
| small tenant (300 chunks), alone | 4.3 ms |
| same tenant, next to 40 000 foreign chunks | 4.2 ms |
| the large tenant itself | 383 ms |

Tenants are isolated. PostgreSQL uses the `document_id` index when the tenant
is small. Retrieval cost depends on **that tenant's own** knowledge base and
nothing else.

The reason this correction is in the document rather than quietly dropped: the
first version was measured, plausible, and wrong. A plan output is evidence
about the query it was run on, not about the system in general.

---

## Options, when someone approaches the ceiling

**Add an HNSW index** (pgvector supports it). It would turn the scan into an
approximate nearest-neighbour lookup and flatten the curve. The cost is that
results become approximate: recall drops below 100%, and *by how much* is
exactly what `rag/test_ocena.py` measures. Adding the index without re-running
that evaluation would trade a latency number for an answer-quality number
without looking at the second one.

**Lower the plan limits** to what is served quickly. Honest, and cheaper than
it sounds — nobody is using more than a fraction of a percent of them today.

**Leave it and watch.** The alert on refusals and the silence alert already
report other kinds of degradation; retrieval latency has no such watch. Adding
one would be the smallest change of the three.

No decision is made here. The measurement exists so that the decision can be
made on numbers instead of a hunch.

---

## What running this costs

The measurement writes real rows. Measured on PostgreSQL 16: 5 000 chunks
occupy 40.1 MB including indexes — **8.2 kB per chunk**. The vector itself is
1536 four-byte floats, so 6 kB of that is the embedding; the rest is row
headers and indexes.

| chunks | disk while running |
|---|---|
| 10 000 | ~80 MB |
| 40 000 | ~320 MB |
| 85 000 | **~680 MB** |

The rows are deleted at the end, including after an error, but they have to fit
somewhere while the measurement runs. **On a server, that somewhere is the
production database.**

The command therefore defaults to 10 000 chunks — enough to see where the curve
stops being linear, and small enough to be safe anywhere. Anything above 25 000
requires `--wiem-ze-pisze-do-tej-bazy`, and the refusal names the size and the
database it would write to.

The first version of the command defaulted to 85 000 and said nothing about
any of this. It was written to answer a question about capacity and would have
been a trap for anyone who trusted it — which is the whole reason the footprint
is measured here rather than estimated.

## Running it on the production instance

Worth doing once, to learn the constant factor between that hardware and the
numbers above. The default size is safe:

```
python manage.py zmierz_skale
```

Around 80 MB while it runs, deleted at the end. Compare the 10 000-chunk row
with the 40 ms measured here; the ratio is what to multiply the rest of the
table by.

## When to measure again

- after adding any index on `documents_documentchunk`,
- after changing chunk size or overlap in `documents/utils/fragmenty.py`,
- after changing the embedding model or its dimensionality,
- after a PostgreSQL major version upgrade,
- once on the production instance, to learn the constant factor between that
  hardware and these numbers.

Write the new numbers into the table above. A table with stale numbers is worse
than none, because somebody will plan around it.
