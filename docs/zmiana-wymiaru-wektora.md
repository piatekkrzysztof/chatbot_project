# Changing the embedding dimension — runbook

**Written for:** the 1536 → 512 migration, 7 September 2026.
**Applies to:** any future change of `WYMIAR_WEKTORA` in `documents/wymiar.py`.

This is a **destructive schema migration**. It deletes every chunk in the
database. Read the whole page before running anything.

---

## What actually changes

Three things move together, and they must move in one deploy:

| | before | after |
|---|---|---|
| `documents/wymiar.py` | 1536 | 512 |
| column `documents_documentchunk.embedding` | `vector(1536)` | `vector(512)` |
| `RAG_MAX_DISTANCE` | 1.0 (Render) / 1.15 (code) | 0.98, both |

Every call to the embeddings API now passes `dimensions=WYMIAR_WEKTORA`.
Without it the model returns its default length and the write fails.

## Why the chunks have to go

Postgres will not convert a 1536-number vector into a `vector(512)` column,
and it is right not to: there is nothing to fill the missing information with.
Truncating to the first 512 numbers is **not** the same as asking the model for
512 — with the `dimensions` parameter the model renormalises the result. A
quiet `USING embedding[1:512]` would produce vectors that look fine and measure
different distances.

Chunks are derived data. Their text lives in `Document.content`, so nothing is
lost permanently — it has to be recomputed.

---

## The sequence

```bash
python manage.py migrate
python manage.py przelicz_fragmenty --wykonaj
```

Then in Render → **chatbot-backend** → Environment, set
`RAG_MAX_DISTANCE` to `0.98`. Web service only — the worker computes vectors
but asks no questions.

That is the whole procedure. Everything below is what to expect and how to
check it.

### Between the two commands

The knowledge base is empty, so `query_similar_chunks_pgvector` returns
nothing and the bot answers that it does not know.

**That is the correct failure.** The bot goes quiet instead of answering from
half a knowledge base or quoting fragments computed at a different dimension.

The window lasts as long as the recomputation. At the state of 7 September
2026 — about 300 chunks across all customers — that is seconds. The migration
prints how many chunks it deleted, so the size of the job is visible at the
moment it is created.

### If the recomputation dies partway

It is safe to re-run. `przelicz_fragmenty` deletes a document's old chunks
before writing new ones, so it never doubles them, and it prints a line per
document, so it is clear where it stopped.

### The watch that catches a forgotten step

The panel's knowledge-base health check (`_zdrowie_bazy_wiedzy` in
`api/views/diagnostyka_zadan.py`) already reports "documents with content but
no chunks" as an outage. If step 2 is skipped or fails, that is where it shows,
without anything new being built for it.

---

## Verifying afterwards

```bash
python manage.py ocen_rag
```

Should print recall 90.9%, silence 75.0%, MRR 0.803 at threshold 0.98. This
runs on frozen vectors and calls no API.

Then check a real knowledge base — the one thing the evaluation corpus cannot
tell you:

```bash
python manage.py zmierz_prog_rag --firma NUMER \
  --pytanie "coś, na co firma odpowiada" \
  --pytanie "coś spoza jej oferty"
```

Covered questions must come back below the threshold, control questions above
it. **Do this.** See "what went wrong the first time" below.

---

## Rolling back

```bash
python manage.py migrate documents 0012
python manage.py przelicz_fragmenty --wykonaj
```

and set `RAG_MAX_DISTANCE` back to `1.0`. The reverse migration also deletes
every chunk, for the same reason in the other direction, so the recomputation
is not optional.

---

## What was measured, and what went wrong the first time

The measurements behind this change are in
[docs/skala-i-wydajnosc.md](skala-i-wydajnosc.md). The short version: same
recall, same silence, 2.9× less disk, 1.6× faster distance computation.

The threshold was nearly set wrong, and the way it was caught is the reason
this section exists.

Sweeping the threshold on the **evaluation corpus** alone suggested moving from
1.00 to **0.90** — the two configurations produced matching recall and silence
numbers there. On a **real knowledge base** that would have cut the question
"w jakich godzinach jesteście otwarci", which sits at distance 0.952 — and sat
at 0.953 *before* the migration. A question the bot could answer would have
stopped being answerable, and no test would have said so.

Measuring the same six questions through both models showed why. Shortening the
vector pulls **everything** closer by the same factor — hits and junk alike:

| question | 1536 | 512 | ratio |
|---|---|---|---|
| how much is a service | 0.778 | 0.736 | 0.945 |
| what are your opening hours | 0.953 | 0.952 | 0.999 |
| do you repair e-bikes | 0.888 | 0.876 | 0.987 |
| how long does a repair take | 0.924 | 0.915 | 0.990 |
| capital of Australia (control) | 1.316 | 1.298 | 0.986 |
| who wrote Lalka (control) | 1.246 | 1.235 | 0.991 |
| | | **mean** | **0.983** |

1.00 × 0.983 ≈ **0.98**, and the evaluation corpus confirms it independently:
at 0.98 it reproduces exactly what 1536 produced at 1.00. Two corpora, one
answer.

Ten fragments of an invented bike shop are enough to detect a regression. They
are not enough to set a threshold. That is what `zmierz_prog_rag` is for, and
skipping it here would have shipped a worse product on numbers that looked
like evidence.

## When to read this page again

- before changing `WYMIAR_WEKTORA`,
- before changing `OPENAI_EMBEDDING_MODEL` — a different model means different
  distances, and the threshold has to be re-measured the same way,
- after the first customer with a large knowledge base signs up, to redo the
  threshold measurement on data that is not the demo.
