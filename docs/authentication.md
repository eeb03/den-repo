# Authentication and dataset ownership

The first real multi-user boundary. Orthogonal to scientific computation: no
threshold, gate, provenance rule or detector behaviour is touched by anything
here.

## Architecture, and why

| Decision | Why |
|---|---|
| **PBKDF2-HMAC-SHA256** (`hashlib`, 600k iterations, per-user salt) | Standard library, so **no new dependency**. RFC 8018, NIST-recommended, Django's default hasher. Critically, **bcrypt silently truncates at 72 bytes** — a long passphrase is quietly weaker than the user believes and two passwords sharing a 72-byte prefix verify identically. PBKDF2 HMACs the password, so its whole length counts. |
| **Server-side sessions**, opaque token in an HTTP-only cookie | Logout must actually revoke. A JWT is valid until expiry; revoking one needs a denylist, which is a session table in disguise. Also no dependency: a JWT needs pyjwt or python-jose. |
| **Only SHA-256 of the token is stored** | A database dump cannot be replayed as live sessions. SHA-256 without a KDF is right *here* and wrong for passwords: the token is 256 bits of `secrets` output, so there is no dictionary to attack. |
| **Cookie**: `httponly`, `samesite=lax`, `secure` from `SUBTERRA_COOKIE_SECURE` | Script cannot read it; nothing is kept in `localStorage`. `secure` defaults off because local development is plain http and a secure cookie would simply never be stored — **set it to 1 in any https deployment.** |

### One thing that had to change

CORS was `allow_origins=["*"]` with `allow_credentials=True`. That combination
is **rejected by every browser** — the spec forbids a wildcard on a credentialed
request — so it could never have carried a session cookie from the Next dev
server. Origins are now explicit, overridable with `SUBTERRA_ALLOWED_ORIGINS`.

## Endpoints

```
POST /api/auth/register   201, signs the new account in
POST /api/auth/login      200, or a UNIFORM 401
POST /api/auth/logout     200 always; revokes the session row
GET  /api/auth/me         the signed-in account, or 401
```

**Login failures are deliberately uniform.** "invalid email or password"
whether the account is absent, the password wrong, or the account disabled —
otherwise the endpoint is an account-existence oracle. Verification also runs
against a dummy hash when no user matches, so timing does not leak what the
message withholds. Registration *does* say when an address is taken: the account
could not be created either way, and hiding it leaves the user no action.

## The authorization model

Deliberately small — three states, no role system:

```
a dataset is VISIBLE to an authenticated user when
    owner_id IS NULL        (system / public reference data)
 OR owner_id  = user.id     (their own)

it is WRITABLE only when owner_id = user.id
```

**System datasets** are the six published corpora — BAM, 4TU, INGV, Lazaresti.
They belong to nobody because nobody uploaded them here, and inventing an owner
would be the same fabrication this codebase refuses everywhere else. Readable by
any signed-in user, writable by none: a reference corpus must not be reprocessed
or deleted out from under everyone else. They were **not** assigned to the first
account that registered.

**Unauthorised access returns 404, not 403.** A 403 confirms the id exists,
which the caller has not earned.

Identity comes from the session and nowhere else. **No route accepts `owner_id`
or `user_id` as an authority field**, and a test walks the request models to
keep it that way. Ownership propagates
`session → ImportJob.owner_id → worker → _run_ingest_pipeline(owner_id=…) → Dataset.owner_id`;
the worker reads it from the job row, never from anything a client sent.

## What stays public

`/api/health`, the three auth endpoints, the static vocabularies and format
lists, and **`/api/benchmark/artifacts*`**. The benchmark artifacts are
published scientific results and THE DESCENT invites readers to check them; a
login wall in front of that evidence would make the invitation false. The
`/benchmark` page is exempted from the workspace gate for the same reason.

`test_the_public_surface_is_exactly_what_we_intend` pins that list, so adding to
it is a deliberate act with a test to update.

## Migration

Migration `002_user_password_hash` adds the credential column. `users` was
created empty by `001`, so `create_all` will not add a column to it — the same
constraint that made `001` necessary, one table along. `user_sessions` is a new
table and needs no migration.

Verified against the live PostgreSQL development database: the column was added,
the six system datasets survived, and their `owner_id` remained NULL.

## Tests

`tests/test_auth_and_ownership.py` (54 tests) covers registration, duplicate
accounts, malformed identity, weak passwords, login success and uniform failure,
logout revocation, token replay after logout, expiry, forged and missing
cookies, and that only a hash is stored.

The isolation matrix builds two users and tries **fourteen id-taking routes**
from each side, plus the body-supplied ids in `views/resolve` and
`overlays/compose`, plus import-job id guessing, plus an explicit spoofing
attempt that posts another user's `owner_id`.

Two guards outlive this commit: `test_every_dataset_route_is_authorised`
enumerates the **live app** and fails if a new dataset route appears without
protection, and `test_the_public_surface_is_exactly_what_we_intend` pins the
unauthenticated set.

### A note on the existing suite

Eighty-odd tests predate authentication and are about conversion, provenance
and view resolution. `tests/conftest.py` gives them a default identity so they
keep testing what they were written for. That is a real trade — **those tests no
longer exercise authorization** — accepted only because authorization has its
own exhaustive suite. The bypass is **opt-out via `@pytest.mark.real_auth`**, so
a new security test cannot inherit it by accident.

## Not done here

No password reset, no email verification, no rate limiting on login, no social
login, no roles or permissions beyond owner/system. Rate limiting is the most
material gap: nothing currently throttles credential guessing.
