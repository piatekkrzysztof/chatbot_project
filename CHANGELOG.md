# Changelog

What changed, from the point of view of somebody using the product — not a git
log. Commits record how the code moved; this records what a customer or an
operator would notice.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning is [semantic](https://semver.org/), counted from the customer's
side: a major release is one after which something they had configured stops
behaving the same way.

The version in `chatbot_project/wersja.py` is served by `/health/`, and a test
fails if it drifts from the newest entry here.

---

## [Unreleased]

Nothing yet.

---

## [1.0.2] — 2026-09-07

Correction to the threshold shipped hours earlier in 1.0.1, plus the production
measurement that 1.0.1 said was missing.

### Fixed

- `RAG_MAX_DISTANCE` **0.98 → 0.96**. At 0.98 the bot answered a question it has
  no knowledge of ("jakie są godziny otwarcia") from an unrelated fragment about
  technical support. Measured on the live knowledge base with
  `zmierz_prog_rag`: everything genuinely covered sits at 0.952 or nearer,
  everything genuinely uncovered at 0.975 or further, and 0.96 is the middle of
  that window. The evaluation corpus gives identical numbers anywhere from 0.90
  to 0.98, so it could not have decided this — a flat sweep means the instrument
  has no opinion, not that either edge is safe.
- `manage.py ocen_rag --przemiataj` now always includes the threshold actually
  in use, and a test fails if it does not. Without it the sweep answers "what
  if" without saying what is.

### Measured

- Production at 512 dimensions: retrieval at 10 000 chunks went from 1 297 ms to
  **388 ms**, and **`shared read` fell from 10 107 blocks to zero**. The table
  now fits in the instance's cache, which is exactly what the migration was for.
  The knee in the curve is gone — growth is linear above a thousand chunks.
- Per-plan retrieval, recomputed: Start ~0.20 s (was 0.7), Grow ~1.0 s (was 3.3),
  Pro ~3.9 s (was 13). Start is comfortable now, Grow is arguable, Pro still
  sells more than we serve.
- **A larger database instance is no longer the answer to slowness.** With no
  disk reads left, the remaining cost is processor time, which more RAM does not
  buy. An HNSW index moved up the list; `halfvec` moved down.

---

## [1.0.1] — 2026-09-07

Nothing a customer should notice. It is here because it required a destructive
migration on their data, and because the ceiling on how large a knowledge base
we can serve moved.

### Changed

- Embeddings are now 512 numbers instead of 1536. Answer quality is unchanged
  where it was measured — same recall, same silence on the evaluation corpus,
  and the same questions answered on a real knowledge base — while the stored
  knowledge base takes **2.9× less space** (2.8 kB per chunk instead of 8.2)
  and distance computation is about 1.6× faster.
- `RAG_MAX_DISTANCE` moved from 1.0 to **0.98**. This is not a new decision:
  shortening the vector pulls every distance in by a factor of 0.983, so 0.98
  is 1.0 expressed in the new scale.
- The code default for `RAG_MAX_DISTANCE` now matches the value the server
  actually runs. Before this it was 1.15 in code and 1.0 on Render, so the
  automated quality measurement described a configuration nobody used.

### Operational

- Deploying this **deletes every chunk** and requires recomputing them:
  `manage.py migrate` then `manage.py przelicz_fragmenty --wykonaj`. Between
  those two steps the bot answers that it does not know. Full procedure and
  rollback: [docs/zmiana-wymiaru-wektora.md](docs/zmiana-wymiaru-wektora.md).
- `manage.py zmierz_skale` now reports the measured size of the chunk table
  next to the figure the code assumes, and warns when they disagree. That check
  immediately caught a wrong estimate in this very change.
- The knowledge-base size alerts (2 500 / 5 000 chunks) were left where they
  are and are now deliberately early: they were derived from the old, larger
  vectors and have not been re-measured on production.

---

## [1.0.0] — 2026-09-04

First release considered fit to sell. The product has been running for the
agency's own site and one pilot; this marks the point where the parts that
break quietly are watched, the backup has actually been restored from, and the
answer quality has a number attached.

### What it does

- A business embeds one `<script>` tag. Visitors ask questions in a chat
  bubble and the bot answers from that company's own pages, documents and FAQs.
- When the knowledge base does not cover a question, the bot says so and offers
  to take a contact detail instead of inventing an answer. The owner gets an
  e-mail, plus a weekly digest of everything the bot could not answer.
- Panel for the owner: knowledge base, conversations, enquiries, widget
  appearance, team, billing, privacy, system health and an audit log.
- Knowledge from uploaded documents (PDF, DOCX, TXT) and from crawled website
  pages, re-fetched on a schedule on the paid plans.

### Security

- Access token lives in memory only; the refresh token is an `HttpOnly`
  cookie. Nothing authentication-related is readable by page scripts.
- Two-factor authentication (TOTP) with single-use backup codes — optional,
  by the owner's choice.
- Login throttled per IP and per account. The account key is a hash, so no
  address is stored in Redis in clear text.
- Audit log of every change made in the panel, readable by the owner.
- Content Security Policy with a per-request nonce; no `unsafe-inline` for
  scripts.
- Server-side route protection for every panel screen.

### Operations

- Alert when a customer's widget starts refusing service, and a separate one
  when a widget that used to be busy goes silent for three days.
- `/health/` reports the real state of the database and the broker, and the
  deployed version.
- Backup command with a documented, timed restore procedure that has been
  rehearsed end to end.
- Scale measurement: how retrieval time grows with the size of a knowledge
  base, set against the plan limits.
- Retrieval quality measured against a fixed corpus, with floors that fail the
  build if answers get worse.

### Known limitations at 1.0.0

Written here rather than left for a customer to find:

- **The plans sell knowledge base sizes the system cannot serve.** Measured on
  the production instance: a full Start plan spends at least 0.7 s on retrieval
  before the model writes anything, Grow at least 3.3 s, Pro at least 13 s. The
  largest real knowledge base today is 246 chunks, about 22 ms, so no customer
  is affected — but the limits are advertised and unservable at their edges.
  Numbers and options in `docs/skala-i-wydajnosc.md`.
- **Retrieval returns nearby chunks for questions the knowledge base does not
  answer.** Vector distance cannot separate "repairs" from "replacement bikes
  during repairs". The model's refusal is what catches this, and it does —
  verified against production, not assumed.
- **`style-src` still allows `unsafe-inline`.** React and Tailwind set styles
  as element attributes. Styles cannot exfiltrate a token, so this is a much
  weaker hole than the script one, which is closed.
- **Uploaded files are not in the database backup.** They live in object
  storage, which survives the database independently — but a single incident
  taking out both would take out the files.
- **No alert on a gradual drop in traffic**, only on silence. A fall from 200
  conversations a day to ten goes unnoticed. Deliberate: the alternative fires
  on every quiet week and stops being read.

[Unreleased]: https://github.com/piatekkrzysztof/chatbot_project/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/piatekkrzysztof/chatbot_project/releases/tag/v1.0.0
