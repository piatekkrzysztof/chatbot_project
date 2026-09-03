# Restoring from backup — runbook and drill record

**Last drilled:** 3 September 2026.
**Result:** restore works. Two bugs were found by running it, both fixed.

Until that date the backup command ended with the line
`Odtworzenie: manage.py loaddata <plik>` and nobody had ever run it. A backup
you have never restored from is not a backup — it is a file you have hopes
about.

---

## What to do when the database is gone

Roughly 12 minutes of work, of which about 12 **seconds** is the machine.
Almost all of the time is provisioning and waiting for a new database.

```bash
# 1. Get the newest backup out of object storage (R2/S3), or take the newest
#    file from backups/ if you still have the disk.

# 2. Point DATABASE_URL / DEV_DB_* at the new, empty database.

# 3. Build the schema. Do NOT skip this — loaddata writes rows, not tables.
python manage.py migrate

# 4. Load the data.
python manage.py loaddata kopia-RRRRMMDD-GGMM.json

# 5. Verify before telling anyone it is over (see "Verification" below).
```

**Do not run `loaddata` into a database that still holds data.** It matches by
primary key: rows in the file overwrite rows in the database, and rows that
exist only in the database stay. The result is a mixture of two states that
nobody planned, and it is very hard to unpick afterwards. Restore into an empty
database or nothing.

---

## Measured, not estimated

Measured on 3 September 2026, local PostgreSQL 16, dump of the development
database: **395 objects, 743 kB**.

| Step | Time |
|---|---|
| `migrate` on an empty database | 7 s |
| `loaddata` of 395 objects | 5 s |
| **Total, machine time** | **12 s** |

These numbers are small because the dataset is small. What they establish is
the shape of the cost: the restore is dominated by the number of objects, not
by the size of the file, and there is no step that takes minutes. A tenant with
50 000 chunks will take proportionally longer to load; the procedure does not
change.

**The number to plan around is not 12 seconds.** It is however long it takes to
provision a new database on Render and change the environment variable — the
restore itself is the fast part.

---

## Verification — what to check before declaring it over

Counts alone are not enough; they were the first thing that looked right in
both a good restore and a broken one. Check these:

```bash
python manage.py shell -c "
from accounts.models import Tenant
from documents.models import DocumentChunk
print('firmy:', Tenant.objects.count())
print('klucze:', sorted(str(t.api_key)[:8] for t in Tenant.objects.all()))
f = DocumentChunk.objects.order_by('id').first()
print('wektor:', len(f.embedding), f.embedding[0])
"
```

- **API keys must be identical to before.** They are pasted into the snippet on
  every customer's website. A restore that issues new ones means phoning every
  customer individually, on the day after an outage.
- **Embeddings must come back at 1536 dimensions with their values intact.**
  A vector silently lost or rounded looks like a healthy restore — rows are
  there, text is there, counts match — and only shows up at the first question
  someone asks the bot.
- **Log in to the panel.** Password hashes travel through JSON as plain text
  and nothing checks them on the way. A broken hash gives you a complete-looking
  user table that nobody can sign in to.

The automated version of all of this is `accounts/tests/test_odtwarzanie.py`.
It runs on every CI build, so a model that stops restoring turns the build red
instead of waiting for a real emergency.

---

## What the backup does NOT contain

- **Uploaded files.** The dump holds the database rows, including the *paths*
  of documents, but not their contents. In production the files live in object
  storage (R2/S3), which survives the database independently — so this is
  normally fine. It is not fine if the same incident takes out both, and it is
  not fine on a local disk deployment, where files vanish with the instance.
- **Content types, permissions, sessions, admin log.** Excluded on purpose:
  migrations recreate them, and including them makes the restore collide with
  rows that already exist. Everyone is logged out after a restore. That is
  correct.
- **Redis.** Queued background jobs are lost. Scheduled tasks resume on their
  own schedule; anything mid-flight has to be triggered again.

---

## What the first drill found

Both of these had been in the code for months and were invisible without
actually restoring.

**1. The guard against overwriting a good backup with an empty one had never
worked.** The command checked `tresc.strip() == "[]"`, but Django with
`indent=2` emits an opening bracket, a line break and a closing bracket — never
those two characters side by side. So the condition was never true. The exact
disaster it was written to prevent — database empty after a failure, the
scheduled backup runs and writes an empty file over the last good copy — was
live the whole time. Now the command parses the JSON and counts objects, which
also proves the file is readable before we trust it.

**2. Restoring re-ran embedding generation for the whole database.** Chunks load
*after* documents, so at the moment each document is saved `chunks.exists()` is
false — and the `post_save` handler queued an embedding job for every single
document. With Celery running that is a paid OpenAI call per document, for data
whose finished vectors are a few screens further down the same file, and the new
vectors would overwrite the restored ones. With Celery down, `enqueue` falls
back to running inline, so the restore itself made those calls one by one and
could die halfway — on the day when everything had already failed once. Fixed by
honouring Django's `raw` flag, which is exactly what it is for.

Neither was found by reading the code. Both appeared within seconds of running
the restore for the first time.

---

## When to drill again

The automated test covers the mechanism on every build. Repeat the full manual
drill — real dump, new database, timed — when any of these change:

- a new model that holds something a customer would miss,
- the storage backend for uploaded files,
- the PostgreSQL major version,
- the hosting provider.

Write the new numbers into the table above. A runbook with stale numbers is
worse than one with none, because somebody will plan around them.
