# Architecture decision records

Only three, and that is deliberate.

Most of the decisions in this project are already written down, in more detail
than an ADR usually carries: the reasoning for pgvector over a separate vector
database, structure-aware chunking, the distance threshold, the tenancy model,
the session design and the rest is in [the README](../../README.md) under *Key
technical decisions* and *Security model*, and the fine-grained reasoning sits
in the module and function docstrings next to the code it explains.

Copying that here would create a second copy that rots. The code changes; the
copy does not, and then a reader has two answers and no way to tell which one
is current.

What is here instead: decisions that are **still open**. Each one gave
something up, each one could reasonably be reversed, and each names the
condition that should make somebody revisit it. Those are the ones worth
recording separately from the code, because the code shows what was chosen and
not what was declined.

| # | Decision | Status |
|---|---|---|
| [001](001-brak-indeksu-wektorowego.md) | No vector index on embeddings | Accepted, revisit at a named threshold |
| [002](002-alarmy-tylko-na-sygnalach-jednoznacznych.md) | Alert only on unambiguous signals | Accepted |
| [003](003-styl-w-atrybutach-zostaje.md) | `style-src 'unsafe-inline'` stays | Accepted, knowingly |

Each record follows the same shape: what was decided, what it costs, what was
rejected, and what would change it.
