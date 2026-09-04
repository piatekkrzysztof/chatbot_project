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
