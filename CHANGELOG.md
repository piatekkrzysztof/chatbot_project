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

## [2.0.7] — 2026-09-11

### Security

- Django admin wymaga MFA także przy wejściu przez starą sesję lub bezpośredni
  adres modelu. Formularz przyjmuje kod z aplikacji lub kod zapasowy.
- Kody MFA i bilety logowania są jednorazowe także przy równoległych żądaniach.
  Bilety wygasają po zmianie hasła lub MFA i mają własny limit błędnych prób.
- JWT powstaje dopiero po obu krokach logowania; awaria wspólnego limitera
  blokuje próby MFA.
- Sekrety TOTP są szyfrowane w bazie i eksporcie Django. Migracja zachowuje
  działające konfiguracje, a polecenie rotacji umożliwia zmianę klucza.

### Operations

- Wdrożenie wymaga okna serwisowego dla migracji sekretów i zachowania
  DJANGO_SECRET_KEY poza hostingiem. Instrukcja: docs/mfa-bezpieczenstwo.md.
- Dodano ręczną komendę retencji wygasłych biletów; harmonogram i odbiór
  produkcyjny pozostają do wykonania.

## [2.0.6] — 2026-09-11

### Fixed

- Konto, firma i okres próbny powstają dopiero po potwierdzeniu e-maila oraz
  ustawieniu hasła. Samo otwarcie linku przez skaner poczty nie aktywuje konta.
- Linki są jednorazowe, ważne 24 godziny, a ponowienie unieważnia poprzedni.
  W bazie zapisywany jest tylko skrót tokena; zgłoszenie nie przechowuje hasła.
- Ponawianie wiadomości ma limity w bazie i w cache; awaria SMTP pozwala wrócić
  do zgłoszenia bez tworzenia częściowego konta lub triala.
- Logowanie zachowuje spacje w haśle, zgodnie z ustawianiem hasła.

### Deployment

- Migracja `accounts.0034_pending_registration`. Istniejące konta pozostają aktywne.
- Wymagany nowy panel z ekranem `/potwierdz-email`, HTTPS w `FRONTEND_URL`
  oraz działający SMTP. Nie są wymagane nowe płatne usługi.
- Rejestracja zwraca 202; płatności uruchamia zalogowany właściciel w panelu.
- Polecenie `purge_pending_registrations` usuwa zgłoszenia starsze niż 7 dni;
  harmonogram i alarm wymagają odbioru operacyjnego.

## [2.0.5] — 2026-09-11

### Fixed

- Rejestracja i przyjęcie zaproszenia sprawdzają hasło w API, zachowując jego
  spacje. Odrzucają zbyt krótkie, popularne, wyłącznie numeryczne oraz podobne
  do danych użytkownika hasła.
- E-mail jest unikalny niezależnie od wielkości liter. Wyścig dwóch rejestracji
  nie pozostawia pustej firmy; nieudane utworzenie okresu próbnego wycofuje konto.
- Zaproszenie jest jednorazowe i przypisane do adresata. Równoległe operacje
  przyjęcia oraz bezpośredniego dodania konta respektują ostatnie miejsce w firmie.
- Publiczne zakładanie kont ma atomowe limity prób we wspólnym cache; awaria
  licznika wstrzymuje operację, zamiast wyłączać ochronę.

### Deployment

- Migracja `accounts.0033_unique_account_email` zatrzyma się przy istniejących
  duplikatach, bez kasowania lub łączenia kont. Wymagany jest działający Redis.
  Szczegóły i otwarty zakres F07: [rejestracja i zaproszenia](docs/rejestracja-i-zaproszenia.md).

## [2.0.4] — 2026-09-10

### Fixed

- Równoległe pytania rezerwują miejsce w miesięcznym pakiecie przed wywołaniem AI.
  Przerwanie strumienia zamyka połączenie z modelem, zapisuje częściową odpowiedź
  i nalicza ją tylko raz; awaria bez odpowiedzi zwalnia rezerwację.
- Odpowiedź rozpoczęta w poprzednim cyklu nie obciąża nowego pakietu.
- Czat testowy nadal nie zużywa płatnego pakietu. Ma osobny limit 100 prób na firmę
  na dobę UTC, walidację długości pytania i wspólny limit równoległych wywołań.
- Limity prób AI działają atomowo w bazie, również dla panelu z JWT i po restarcie
  cache. Operator może sprawdzić i uzgodnić rezerwacje pozostałe po awarii procesu.

## [2.0.3] — 2026-09-10

### Fixed

- Document uploads validate the actual PDF, DOCX, TXT or Markdown content before
  saving or scheduling embeddings. Limits apply to received bytes, extracted
  text, PDF pages/streams and expanded DOCX archives. Empty, encrypted or
  unsupported documents return an actionable error.
- File parsing runs in a separate process with memory, CPU and wall-clock limits,
  a clean environment and one parser at a time per application instance. Busy
  or unavailable parsers reject uploads without storing them. Embeddings are
  scheduled once after successful extraction.
- New logos and avatars accept PNG, JPEG and WebP, enforce size/pixel limits,
  reject animation, and are rebuilt as PNG without metadata or appended content.
  Transparency and photo orientation are preserved.
- Failed background file extraction exposes a readable error instead of leaving
  the document indefinitely processing. Storage exception details stay private.

### Operations

- Deploy backend and worker together and run the additive migration
  `documents.0015_document_processing_error`. No new environment variables.
  See `docs/bezpieczne-uploady.md` for limits, rollout and remaining boundaries.

## [2.0.2] — 2026-09-10

### Fixed

- Website imports, crawling and sitemap discovery only connect to verified public
  HTTP/HTTPS addresses on ports 80/443. Every redirect is checked again; DNS
  rebinding cannot change the address used by the connection. HTTPS still checks
  the original hostname and certificate. Local network URLs and URLs containing
  credentials are rejected, including sources saved before this release.
- Downloads have time, size and redirect limits, with a shared network budget
  for each crawl. Compressed responses and nested sitemaps cannot expand without
  limits; sitemap XML cannot load external entities. Crawling uses exact hostname
  matching and bounded link queues.
- Existing document contents and URL spelling remain unchanged. Failed imports
  retain their error status; an empty set of allowed links is not reported as a
  successful refresh.

### Operations

- Deploy backend and worker together. There are no migrations or new environment
  variables. See `docs/bezpieczne-pobieranie-stron.md` for the limits and supported
  website behavior. Private sites, custom ports, and oversized pages now fail
  explicitly instead of being fetched.

## [2.0.1] — 2026-09-10

### Fixed

- Remote backups report success only after reading the stored ciphertext back
  and verifying that it matches the uploaded bytes. Storage failures stop the
  command without printing provider error details that may contain credentials.
- Backup jobs validate models without importing HTTP routes, so a dedicated
  backup host does not need an OpenAI API key merely to start the command.
- Operators can run `check_backup` to detect missing, stale, corrupt or
  undecryptable copies. Its age check uses the authenticated encryption timestamp;
  renaming or re-uploading an old copy does not make it fresh.

### Operations

- Added a separate, opt-in Render cron template and a deployment/restore runbook.
  Merging this release does not create scheduled jobs or enable notifications.
  Database PITR, uploaded-file backups and a full staging restore remain separate
  acceptance requirements.

## [2.0.0] — 2026-09-09

### Security

- New documents use a dedicated private store and unpredictable names scoped to
  the company. Downloads check the authenticated company before opening a file;
  public widget keys cannot download originals. Public logos retain their store.
- Backups are authenticated Fernet ciphertext, including local copies. Remote
  backups require a separate private bucket and never create a local plaintext
  dump. Missing keys, damaged copies and existing output files stop the command.
- A resumable migration copies and verifies legacy documents and encrypts legacy
  JSON backups. Source deletion requires a separate explicit option. Existing
  files remain readable during the transition, without publishing their URLs.

### Deployment required

- This major release changes storage configuration and the backup format.
  Configure private document storage on web and worker before deployment, and
  private backup storage plus an independent encryption key on the backup host.
  New document uploads return 503 until configured. Restore encrypted backups
  using `decrypt_backup` before `loaddata`.
- Run the field-state migration, migrate existing objects, verify cloud access
  policies and then disable legacy reads. Follow
  [the deployment and migration guide](docs/prywatne-pliki-i-kopie.md).
  The SQL schema and existing document keys do not change.

## [1.0.6] — 2026-09-09

### Security

- Tenant isolation and team authorization now bind access to the authenticated
  user's company, reject conflicting widget keys, and protect the last active
  owner. CSV imports and exports use the authenticated company (audit stage 1).
- Production Docker builds include only selected application files and runtime
  dependencies. Environment files, backups, local databases and test tools are
  excluded. Docker Compose explicitly uses the development target.
- Django REST framework 3.17.2 fixes CVE-2026-73228 and CVE-2026-73229: request
  body size limits and protected-data exposure through AdminRenderer.

### Fixed

- Retention preserves old conversations with recent messages, including data
  saved before this fix. Message writes update activity atomically; retention
  skips conversations locked by concurrent writes. Prompt logs, usage logs and
  contact requests still expire independently by their creation time.

### Changed

- The knowledge-base size alerts move from 2 500 / 5 000 chunks to **15 000 /
  25 000**. The old pair came from the knee of the curve before the vectors were
  shortened; afterwards it described 60 ms and 120 ms — an alert firing five
  times earlier than anything a visitor could feel. The new pair is derived from
  the time itself: half a second and one second of retrieval, taken from the
  production curve rather than from a single rate.
- The alert message now interpolates over the measured points instead of
  multiplying by one constant. The curve is not a straight line — 23 µs per
  chunk while the table fits in cache, 53 µs once it does not — so one constant
  had to be wrong at one end.

### Internal

- `api/utils/chat_engine.py` split into three: the `[BRAK_ODPOWIEDZI]` protocol
  moved to `api/utils/pokrycie.py`, the system prompt to
  `api/utils/prompt_systemowy.py`, leaving 401 lines from 636. Not for the line
  count — both are concepts with several consumers, their own tests and their own
  way of failing silently.

---

## [1.0.5] — 2026-09-08

### Changed

- **The Pro plan's knowledge base limit drops from 100 MB to 50 MB.** Measured
  on production, 100 MB is about 5.2 seconds of retrieval before the model
  writes its first word. That is not a slow answer, it is a broken one, and the
  price list was selling it. Nobody is affected today: the largest real
  knowledge base is 246 chunks, 0.24% of the old limit.
- Start (5 MB) and Grow (25 MB) are unchanged and now sit on measured points:
  0.19 s and 1.04 s of retrieval.

### Added

- A test that fails if any plan sells a knowledge base costing more than three
  seconds of retrieval. Before it, the figure in the price list and the figure
  from the measurement had nothing connecting them — which is why 100 MB
  survived four months.

### Measured

- Production up to 40 000 chunks. **The knee did not disappear with the shorter
  vectors, it moved.** Up to 10 000 chunks nothing is read from disk and a chunk
  costs 23 µs; at 40 000 the query reads 110 MB — the whole table — on every
  question, and a chunk costs 53 µs.
- This corrects what was written here yesterday. "The query is CPU-bound and a
  larger instance would not help" was measured at 10 000 chunks and is true only
  there. Above roughly 25 000 it is memory-bound again, and more RAM is exactly
  the fix. Any answer to "would a bigger database help" has to name the size it
  is answering for.
- Chunk footprint confirmed a third time: 2.8 kB, now at 40 000 chunks.

---

## [1.0.4] — 2026-09-08

### Fixed

- **Saying hello no longer triggers a request for the visitor's contact
  details.** A visitor typing "cześć, jest tam kto?" got a warm reply and then,
  in the same breath, a contact form. Verified on production before the fix.
- The same greetings were filed as knowledge gaps, so the weekly report advised
  the owner to "add an answer for «hello»" to their knowledge base, and the
  coverage figure on the dashboard was pulled down by visitors being polite.
- One line caused all three: when retrieval returned nothing, the answer was
  recorded as "the bot did not know". That was the only signal available before
  the model started declaring gaps itself with `[BRAK_ODPOWIEDZI]`. Now the
  marker decides, and small talk is recorded as `rozmowa` — a source with no
  consequences.
- A retrieval failure is deliberately still counted as a gap. The question may
  have been real and the bot answered without its knowledge base; recording that
  as a friendly chat would have hidden a fault exactly when it matters.

This fix is only safe because of 1.0.3. Until yesterday the model often answered
off-topic questions without the marker, so "no marker" did not mean "nothing to
report". It does now: correct refusals measure 100%, and `ocen_generowanie`
watches that number.

### Added

- `ocen_generowanie` now measures the recorded **source**, not only the marker.
  The gap it closes is the one that produced this release: a greeting answered
  warmly passed every existing check while still asking the visitor for their
  phone number.

---

## [1.0.3] — 2026-09-08

### Changed

- **The bot no longer answers questions that have nothing to do with the
  company.** Asked for the capital of Australia or a square root, a bike shop's
  assistant used to answer from world knowledge — once with a wrong number. It
  now says it does not have that information and offers contact, like any other
  question it cannot answer from the knowledge base.
- That matters beyond looking unprofessional: those answers carried no
  `[BRAK_ODPOWIEDZI]` marker, so no enquiry reached the owner and nothing landed
  in the knowledge-gap report, while the visitor's message still counted against
  the customer's plan.
- Greetings and thanks are explicitly exempt. Without that exemption the same
  rule answered "Cześć, jak się masz?" with "I do not provide information on
  that subject" — in the first line of the conversation — and filed it as a
  knowledge gap.

Measured on the evaluation corpus, gpt-4o-mini at production temperature,
5 repetitions: correct refusals **70.8% → 100.0%**, with false refusals,
wrongly-refused greetings and grounding all unchanged at 0.0% / 0.0% / 100.0%.
Same figures on gpt-5.6-luna, so the rule is not tuned to one model. Cost:
**+145 tokens per message**, mostly input.

### Added

- `manage.py ocen_generowanie` — measures what the chat model does, which
  nothing measured before. `ocen_rag` covers retrieval only, and the chat model
  does not touch retrieval, so it would report identical numbers no matter what
  `OPENAI_CHAT_MODEL` was set to.
- The thing it watches is `[BRAK_ODPOWIEDZI]` — the marker by which the model
  says it cannot answer. Contact capture, the enquiry e-mail, the knowledge-gap
  report, the refusal alert and the threshold measurement all hang off it, and
  it is a protocol the **model** keeps, not the code. A model that stops
  emitting it fails silently.
- Takes several models at once and prints them side by side, with tokens and
  latency, so a model change can be decided on numbers.
- The evaluation corpus now has a fifth group: greetings and small talk, with a
  third expected behaviour distinct from both answering and refusing. The first
  attempt at this prompt change broke greetings while the evaluation reported
  perfect scores — there was not a single greeting in the corpus.

### Fixed

- **Switching to any current OpenAI model would have broken every chat request,
  and no alert would have fired.** Newer models (gpt-5.x) reject `max_tokens`
  and reject any `temperature` other than the default — with a 400, on every
  question. The chat engine catches that and returns its fallback message, so
  the bot would have told every visitor "something went wrong". Meanwhile
  retrieval still returns fragments, so the log records source "document", the
  refusal alert sees no rise and the silence alert sees no silence. The customer
  would have been the one to notice.
- Both call sites now send `max_completion_tokens` (accepted by old and new
  models alike) via one shared helper, and send `temperature` only when it is
  set. An empty `OPENAI_TEMPERATURE` now means "do not send the parameter".
- `manage.py sprawdz_model` turns that outage into one line in a terminal, for
  one API call, before deploying.

### Measured

- Baseline for `gpt-4o-mini`: correct refusals 70.8%, false refusals 0.0%,
  answers grounded in a retrieved fact 100.0%, 470 tokens and 0.8 s per answer.
- Every failure is in the "off topic" group — the bot answers "what is the
  capital of Australia" from world knowledge, and once returned a wrong square
  root. On the harder and commercially relevant group — trade questions this
  company does not answer — it keeps to the marker.
- One case is worse than a wrong answer: asked who wrote *Lalka*, the model
  replied "I do not have that information, please contact the company" **without
  the marker**. A refusal the system counts as an answer: no contact offer, no
  entry in the gap report.

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
