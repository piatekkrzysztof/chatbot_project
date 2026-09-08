# 004 — No enrichment of chunks before embedding

**Status:** rejected after measurement
**Date:** 8 September 2026

## Decision

Chunks go to the embedding model as they are, with only the document name
prepended (`tekst_do_wektora` in `documents/utils/fragmenty.py`). Nothing is
generated and added to improve how they are found.

## The problem it was meant to solve

Retrieval recall sits at **90.9%** — one in eleven paraphrased questions finds
nothing. The failing case in the evaluation corpus is concrete:

> **"Czy pracujecie w weekend?"** against a fragment reading *"Sklep i serwis
> są czynne od poniedziałku do piątku 9-18 oraz w soboty 10-14. W niedziele
> nieczynne."*

The distance is **1.024**, the threshold is 0.96, so the bot says it does not
know — about something its knowledge base answers plainly.

This is a vocabulary mismatch, not a threshold problem. The word "weekend" does
not appear in the fragment, so **keyword search would not find it either** —
hybrid retrieval is not the answer here. Lowering the threshold is not either:
on real customer data the usable window is 0.952–0.975
([settings/base.py](../../chatbot_project/settings/base.py)).

## The idea, and why it looked good

Ask the model, once per chunk at ingest, to write a line of words a customer
might use that the chunk does not contain. Embed *that line plus the chunk*,
store the chunk unchanged. The mechanism already exists — this is exactly what
the document name does today.

A hand-written probe supported it:

| | distance |
|---|---|
| fragment as it is | 1.024 → cut |
| fragment + *"godziny otwarcia, kiedy czynne, praca w weekend, soboty i niedziele"* | **0.940** → passes |

## What the measurement said

Two attempts, both on the full corpus through `rag/ocena`, both measuring
**both sides** of the trade — recall and silence:

| | recall | first place | MRR | silence |
|---|---|---|---|---|
| as it is today | 90.9% | 72.7% | 0.803 | **75.0%** |
| enrichment, question-shaped | 90.9% | 72.7% | 0.818 | 75.0% |
| enrichment, keyword-shaped | 90.9% | 72.7% | 0.773 | **50.0%** |

**Neither found the weekend.** Both times the model wrote paraphrases of what
the fragment already says — *"godziny otwarcia, dni robocze, harmonogram,
dostępność"* — and never the umbrella word a visitor actually types.

The second attempt was worse than doing nothing. Asked for missing words, the
model produced domain-generic ones (*serwis, naprawa, usługa*), and those are
generic precisely because they fit every fragment: "czy naprawiacie hulajnogi
elektryczne" started matching the chain-price fragment. Silence fell by a third.

## Why it stops here rather than at a third attempt

The one failing question is known, so any further tuning of the instruction
would be tuning against it. On a corpus with one instance of this failure, that
produces a number that looks like a result and is an artifact of the author
knowing the answer.

## What answers the problem instead

The product already has the mechanism, and this measurement is a point in its
favour rather than a hole in it:

1. the bot refuses, honestly, instead of quoting something unrelated,
2. the question lands in the knowledge-gap report (`chat/raport_luk.py`),
3. the owner adds it as an FAQ entry — an exact answer, in the visitor's own
   words, with nothing guessed.

Vocabulary a business's customers use is knowledge about that business. Guessing
it centrally is a worse instrument than asking the person who has it.

## When to revisit

- if the gap report at a real customer fills up with paraphrases of questions
  the knowledge base **does** answer — that would mean the loop above is too
  slow, not that it is wrong,
- if recall drops below 90% on the corpus for a reason other than this one,
- if a corpus with more than one vocabulary-mismatch case exists, so an
  instruction can be tuned without tuning against the single known failure.
