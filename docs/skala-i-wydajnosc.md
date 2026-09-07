# How far this scales, measured

**Measured:** 4 September 2026, local PostgreSQL 16 with pgvector.
**Repeat it yourself:** `python manage.py zmierz_skale`

> **Read this first.** On 7 September 2026 the vector was shortened from 1536
> to 512 dimensions — the change this document argued for. Everything in the
> "The numbers" section below was measured **before** that, at 1536, and is
> kept because the *shape* of the curve is what it explains. The post-migration
> numbers are marked as such, and the production ones do not exist yet: see
> [What is still unmeasured](#what-is-still-unmeasured).

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

## The numbers (at 1536 dimensions, before the migration)

Measured on the **production instance** (Render, Frankfurt) on 4 September
2026. These are the numbers that matter; the development laptop is below for
comparison and to show why it must not be used to draw conclusions.

| chunks | median | worst |
|---|---|---|
| 1 000 | 90 ms | 197 ms |
| 5 000 | 396 ms | 902 ms |
| 10 000 | **1 297 ms** | **2 288 ms** |

Growth is worse than linear, and the knee sits between 5 000 and 10 000:
doubling the data multiplies the time by 3.3. Below that, five times the data
costs 4.4 times the time.

The query plan explains the shape: a sequential scan over the tenant's chunks,
computing an L2 distance for each, then a sort. There is **no vector index** on
the embedding column — only the primary key and the foreign key to the
document. The knee on top of that is consistent with the working set outgrowing
what the database instance can keep in memory: at 10 000 chunks the table is
around 80 MB.

### Why the laptop numbers are kept

| chunks | laptop | production | ratio |
|---|---|---|---|
| 1 000 | 7 ms | 90 ms | 13× |
| 5 000 | 22 ms | 396 ms | 18× |
| 10 000 | 40 ms | 1 297 ms | **32×** |

The ratio is not constant. A development machine is not a slower version of the
server — it is a different shape, and it hides the knee entirely. The first
version of this document drew a conclusion from the laptop column alone and got
the margin wrong by more than an order of magnitude.

---

## Where this meets the price list

A chunk holds at most 1200 characters and overlaps its neighbour by 180, so
each one advances about 1020 characters of source text.

| plan | knowledge base | chunks | retrieval, production |
|---|---|---|---|
| start | 5 MB | ~5 140 | **at least 0.7 s** |
| grow | 25 MB | ~25 700 | **at least 3.3 s** |
| pro | 100 MB | ~102 800 | **at least 13 s** |

Those are conservative: they extrapolate the linear rate from the 5 000–10 000
segment, and the real curve is worse than linear. Read them as floors.

**These three latencies are from before the 512-dimension migration** and are
the most stale numbers on this page. They should be better now — the chunk
count per plan does not change, but each chunk is 2.8 kB instead of 8.2, so the
memory effect that produced them is weaker. By how much is unmeasured;
[What is still unmeasured](#what-is-still-unmeasured) says how to find out. The
argument below does not depend on the exact figures, only on their order.

**The plans as priced sell knowledge base sizes the system cannot serve.** Not
"would be slow at" — cannot serve. Thirteen seconds before the model starts
writing is not a slow answer, it is a broken one, and the Grow plan at three
seconds is not much better.

The Start plan is the one that matters most, because it is the cheapest and
will be the most sold: filled to its 5 MB limit it spends around 0.7 s on
retrieval alone, before generation begins.

### Where real customers sit

The largest actual knowledge base today is **246 chunks** — about 22 ms on
production, and 0.24% of the Pro limit. No customer is in trouble.

But the headroom is roughly twenty times smaller than the first version of this
document claimed, because that version was measured on a laptop. The distance
between "nobody is close" and "the cheapest plan is already uncomfortable when
full" is the whole reason this was re-measured on the real machine.

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

## The cheaper option, measured — and then taken

The obvious lever is an approximate index. There is a cheaper one that nobody
had looked at, including this document until now: **ask the embedding model for
fewer dimensions.**

This section started as a proposal. On 7 September 2026 it became the change
that shipped; the runbook is
[docs/zmiana-wymiaru-wektora.md](zmiana-wymiaru-wektora.md).

`text-embedding-3-small` accepts a `dimensions` parameter. The model is trained
so that a shorter vector degrades gracefully rather than falling apart, so 512
dimensions is not "the first third of a 1536-dimension vector" — it is a vector
the model produced to be used at that length.

### Quality: essentially unchanged

Measured on the same corpus and questions as `rag/test_ocena.py`. The method
was checked first against the known pgvector result, and reproduced 90.9% /
75.0% exactly before being used for anything else.

| | recall | silence | MRR |
|---|---|---|---|
| 1536 dimensions, threshold 1.00 | 90.9% | 75.0% | 0.818 |
| **512 dimensions, threshold 0.98** | **90.9%** | **75.0%** | **0.803** |

Same recall, same silence, ranking quality 1.8% relatively worse. **The
threshold has to move**, because shortening the vector pulls every distance in
by the same factor — hits and junk alike. Measured across both corpora that
factor is **0.983**, so 1.00 becomes 0.98.

The first version of this section said the threshold had to move to **0.90**,
which came from sweeping the evaluation corpus alone. It was wrong, and it
would have cut a real question a real customer asks. The full account, with the
per-question measurement through both models, is in the runbook:
[docs/zmiana-wymiaru-wektora.md](zmiana-wymiaru-wektora.md#what-was-measured-and-what-went-wrong-the-first-time).

The lesson generalises past this migration: a synthetic corpus is an instrument
for detecting regressions, not for setting thresholds. The two jobs look
identical from the outside — both produce a table of numbers per threshold.

### Speed and size: measured, not extrapolated

| chunks | 1536 | 512 | faster | 1536 size | 512 size | smaller |
|---|---|---|---|---|---|---|
| 2 000 | 10.6 ms | 6.2 ms | 1.7× | 16.0 MB | 5.5 MB | 2.9× |
| 5 000 | 23.8 ms | 15.5 ms | 1.5× | 39.9 MB | 13.7 MB | 2.9× |
| 10 000 | 52.6 ms | 31.5 ms | 1.7× | 79.8 MB | 27.3 MB | 2.9× |

The speed-up is **1.6×, not 3×** — computing distances is not the whole cost of
the query. The size reduction is nearly the full 3×.

Confirmed after the migration through the real code path rather than a
side-by-side script: `zmierz_skale --do 5000` on the same laptop reported 13.8 MB
for 5 000 chunks — **2.8 kB per chunk**, matching the 27.3 MB at 10 000 above.

That number was nearly wrong in the other direction. The command first
estimated the footprint as "vector plus a constant overhead": 8.2 kB measured
at 1536 minus 6.0 kB of vector left 2.2 kB, giving 2.0 + 2.2 = **4.2 kB** at
512. The measurement said 2.8. The overhead is not constant — a 1536-dimension
vector goes out of line into TOAST, with its own index, and a shorter one pays
less for that. The formula looked principled and was off by half.

It was caught because the command now prints its estimate next to the measured
growth of the table and warns when they diverge by more than 15%. A constant
that nothing ever checks is a guess with a comment above it.

### Why the size number may matter more than the speed one

These were measured on the development laptop, where every block is already in
memory. On production the knee between 5 000 and 10 000 chunks lines up with
the table outgrowing what the database can cache: 82 MB at 10 000 chunks, on an
instance whose cache is a fraction of that.

At 512 dimensions the same 10 000 chunks are 27 MB — back under the cache on a
small instance. If the production knee really is a memory effect, this removes
it without buying anything, and the gain there would be larger than the 1.6×
measured here.

### The "if" is answered: it is memory

Run on production 7 September 2026, at 10 000 chunks:

```
Buffers: shared hit=20054 read=10107
```

**10 107 blocks — about 79 MB — came from disk.** That is essentially the whole
table, on a query issued after nine identical ones had already run. The data
does not stay cached: each scan evicts what the previous one loaded, so every
question pays the full disk cost.

A third of all block reads are from disk. On the laptop the same query reads
zero blocks from disk, which is why it never showed the knee.

So the answer to "would a larger database instance help" is **yes** — this is
exactly the shape that more memory fixes.

But the same table at 512 dimensions is **27 MB instead of 80**. If the cache
is anywhere between those two numbers, shortening the vector removes the disk
reads without renting anything. That is the cheaper path to the same effect,
and it is measurable before committing to it.

### A caveat about the timings, not the block counts

Two production runs of the same measurement, days apart:

| chunks | run 1 | run 2 | difference |
|---|---|---|---|
| 1 000 | 90.0 ms | 88.7 ms | 1% |
| 5 000 | 396.1 ms | 595.8 ms | **50%** |
| 10 000 | 1 297.4 ms | 991.7 ms | **31%** |

Only the smallest point is stable. Above it the instance is noisy enough that a
single number should not be trusted to two significant figures, and the exact
position of the knee is softer than the first table suggests.

The block counts do not have this problem: they are counts, not timings, and
they say the same thing on every run.

## What is still unmeasured

**Production, at 512 dimensions.** The whole "The numbers" table, the knee, and
the per-plan latencies were measured at 1536. The disk reads that motivated the
migration were measured at 1536. Nothing in this document says what production
does *now*.

The expected direction is clear — 27 MB instead of 80 should fit in cache where
80 did not — but expected is not measured, and this document has already been
wrong once about the size of a margin. One run settles it:

```
python manage.py zmierz_skale
```

Around 14 MB while it runs at the default size, deleted at the end. What to
look at: `shared read` in the query plan. If it is near zero where it was
10 107, the migration removed the bottleneck and the per-plan table above is
obsolete in the good direction.

**Until then**, the alert thresholds in `accounts/rozmiar_bazy.py` (2 500 and
5 000 chunks) stay where they are. They were set from the 1536 measurement and
are now pessimistic — they will fire earlier than necessary. That is the right
direction to be wrong in: the cost is one unnecessary email, the cost of the
other direction is a slow bot that we hear about from the customer.

## Options, when someone approaches the ceiling

Shortening the vector was the first of these and it is done. In order of what
to reach for next:

**Halve the storage again with `halfvec`.** pgvector's 16-bit float type would
take 2.8 kB per chunk down to roughly 1.4. Same trade-off shape as this
migration — measure quality first, on real data, not only on the corpus.

**Add an HNSW index** (pgvector supports it). It would turn the scan into an
approximate nearest-neighbour lookup and flatten the curve. The cost is that
results become approximate: recall drops below 100%, and *by how much* is
exactly what `rag/test_ocena.py` measures. Adding the index without re-running
that evaluation would trade a latency number for an answer-quality number
without looking at the second one.

**Lower the plan limits** to what is served quickly. Honest, and cheaper than
it sounds — nobody is using more than a fraction of a percent of them today.
Still open as of 7 September 2026, and now needs redoing against post-migration
numbers rather than the ones above.

**Rent a bigger database.** The only option on this list with a recurring cost,
and the only one that helps without touching anything. Worth reconsidering only
after the production measurement above shows what is left of the problem.

---

## What running this costs

The measurement writes real rows. Measured on PostgreSQL 16 at 512 dimensions:
5 000 chunks occupy 13.8 MB including indexes — **2.8 kB per chunk**. Before
the migration the same 5 000 chunks took 40.1 MB, or 8.2 kB each.

| chunks | disk while running (512) | before (1536) |
|---|---|---|
| 10 000 | ~27 MB | ~80 MB |
| 40 000 | ~110 MB | ~320 MB |
| 85 000 | **~230 MB** | ~680 MB |

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

Around 27 MB while it runs, deleted at the end. Compare the 10 000-chunk row
with the 31.5 ms measured here; the ratio is what to multiply the rest of the
table by. Before doing that, check `shared read` — see
[What is still unmeasured](#what-is-still-unmeasured).

## When to measure again

- after adding any index on `documents_documentchunk`,
- after changing chunk size or overlap in `documents/utils/fragmenty.py`,
- after changing the embedding model or its dimensionality,
- after a PostgreSQL major version upgrade,
- once on the production instance, to learn the constant factor between that
  hardware and these numbers.

Write the new numbers into the table above. A table with stale numbers is worse
than none, because somebody will plan around it.
