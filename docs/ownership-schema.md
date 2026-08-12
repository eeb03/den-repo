# Ownership schema

The database foundation for user-owned datasets. **The schema exists;
authentication does not.** Nothing creates a user, nothing reads an owner, and
no request is associated with an identity.

```
User ──< Dataset
  └────< ImportJob
```

| Column | Type | State |
|---|---|---|
| `users.id / email / display_name / is_active` | new table | empty |
| `datasets.owner_id` | nullable, indexed, FK → `users.id` | NULL on every row |
| `import_jobs.owner_id` | nullable, indexed, FK → `users.id` | NULL on every row |

## Why the columns exist before the login does

Adding ownership to an empty `users` table is free. Adding it *after* accounts
exist means answering, retroactively, who owns data that was uploaded by
nobody — a question with no correct answer. Doing the schema first means the
authentication task can be about authentication.

**No placeholder owner is written.** Not `"default-user"`, not `"anonymous"`,
not `"system"`. A fabricated owner would make every dataset look owned by
somebody who does not exist, and would later be indistinguishable from a real
one. `NULL` means exactly what it says: uploaded before ownership existed, by an
unauthenticated caller. A test (`test_no_code_invents_a_placeholder_owner`)
fails the build if a placeholder appears in `api/`, `database/` or `jobs/`.

`users` deliberately has **no credential column**. Password hash vs OIDC subject
vs API token is a decision for the authentication task; guessing here would bake
in a choice that task should make. A test asserts no such column exists.

## Migration mechanism

There was no migration framework, and `Base.metadata.create_all` creates
*missing tables* but never alters an existing one. So `users` and `import_jobs`
appear on their own, while `datasets.owner_id` — a column on a populated table —
does not. Left unmigrated, the model would emit `SELECT datasets.owner_id`
against a table without it and take down the dataset listing, the workspace and
the import report together.

`database/migrations.py` is a ~100-line explicit migration runner:

- **Idempotent** — every migration inspects the live schema before acting, so
  running it twice, or against an already-correct database, is a no-op. It is
  called from `init_db()` on every startup, after `create_all`.
- **Recorded** — applied ids land in `schema_migrations`, so history is
  inspectable rather than inferred.
- **Additive only** — no `DROP`, no `DELETE`, no `TRUNCATE`, no `UPDATE`. A
  statement that could destroy data has no business running unattended at
  startup, and a test greps the module to keep it that way.

**Why not Alembic.** It is the right tool for a schema with real churn and may
well be right here later. It is not right for one nullable column: it brings a
migrations directory, an `env.py`, a version graph and an autogenerate step
whose diffs still need reading by hand. This module can be replaced by Alembic
later without any model or data change.

### Dialect divergence, stated rather than hidden

PostgreSQL and SQLite both support `ALTER TABLE … ADD COLUMN`. Only PostgreSQL
supports adding a **foreign-key constraint** to an existing table; SQLite
cannot, and rebuilding the table to fake it would be exactly the destructive
operation this module refuses to perform automatically.

So:

| | column | index | FK constraint |
|---|---|---|---|
| fresh database (`create_all`) | ✅ | ✅ | ✅ |
| existing PostgreSQL (migrated) | ✅ | ✅ | ✅ |
| existing SQLite (migrated) | ✅ | ✅ | ❌ |

Nothing depends on the constraint yet — the column is nullable and unread until
authentication exists — and the live deployment is PostgreSQL, where it is
present. Verified against the real development database: the column, the index
and `fk_datasets_owner_id_users` were all added, all 6 existing datasets
survived with `owner_id IS NULL`, and a second startup was a no-op.

## Backfill strategy

There is nothing to backfill, and that is the point. When authentication lands:

1. Accounts are created; `users` gains rows.
2. New uploads set `owner_id` from the authenticated request. **Nothing else
   changes** — the column and its index already exist.
3. Historical rows stay `NULL` unless a human deliberately assigns them. They
   were uploaded by an unidentified caller and the database should keep saying
   so rather than assert an owner nobody verified.
4. Only once every row is genuinely owned may `owner_id` become `NOT NULL`, and
   that is another explicit migration.

## What is still unsafe about multi-user

Until authorization is written, **every dataset is visible to every caller** and
all uploads share one directory tree. `GET /api/datasets/` has no owner filter,
and neither do the object, label, overlay or provenance routes. Ownership
columns are a prerequisite for fixing that; they do not fix it. Do not expose
this deployment to multiple untrusted users on the strength of this change.
