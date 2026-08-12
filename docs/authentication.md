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

## Login rate limiting

Login is the one endpoint a stranger can call repeatedly with attacker-chosen
input. PBKDF2 at 600k iterations makes each guess expensive, but expensive is
not limited.

| | |
|---|---|
| **Storage** | the application database — `login_attempts`, one row per bucket |
| **Counting** | atomic `INSERT … ON CONFLICT DO UPDATE … RETURNING`, never read-modify-write in Python |
| **Keys** | `ip:<peer>` and `email:<submitted address>` — both checked |
| **Policy** | 10 failures per IP, 20 per account, in a 15-minute fixed window |
| **Blocked** | `429` + `Retry-After`, generic message |
| **Recovery** | the window expires on its own; there is no lockout flag |

**Why the database and not Redis:** there is no Redis. The deployment is `db`
and `api`, and the only mention of Redis in this repository is the comment
explaining why the job runner does not use one. PostgreSQL is already the shared,
durable state; adding a broker for one counter would be a new operational
dependency for something the existing store does. **Why not a Python dict:** it
resets on restart, handing an attacker a fresh budget every deploy, and is
per-process, so N workers would multiply the limit by N.

**Two keys, because either alone is wrong.** Per-IP alone lets a botnet try one
password against every account. Per-account alone lets an attacker lock a victim
out of their own account — a defence turned into a weapon. The per-account
budget is therefore the more generous, and **neither ever locks**: the window
expires by itself.

**Only failures count**, and a success clears both counters, so nobody is
throttled by their own earlier typos and a shared office address is not punished
for having many legitimate users.

**No new enumeration channel.** Counters are keyed on the submitted address
whether or not it exists, so the 429 is identical for a real address and an
invented one. A blocked bucket also refuses the *correct* password — otherwise
the 429 would answer only wrong guesses, which is an oracle.

**Client address:** `request.client.host`, the peer. `X-Forwarded-For` is
consulted only when `SUBTERRA_TRUST_PROXY_HEADERS` is set, because trusting it
unconditionally lets any caller choose their own bucket by sending a header —
which deletes the limit rather than weakening it. There is no trusted-proxy
configuration in this application, so it defaults off.

**Failure policy: fail closed**, and it costs nothing. If the counter cannot be
read or written, login is refused (`503`). That is normally a hard trade, but the
limiter shares its store with the credential store — there is no state in which
this table is unreachable and login could otherwise have succeeded.

**A known cost:** the window is fixed, not sliding, so an attacker can spend a
budget at the end of one window and another at the start of the next, briefly
doubling the rate. Accepted for a counter that is one row and one statement.

Configuration, via environment variables (the mechanism `auth/sessions.py`
already uses): `SUBTERRA_LOGIN_IP_MAX` (10), `SUBTERRA_LOGIN_EMAIL_MAX` (20),
`SUBTERRA_LOGIN_WINDOW_SECONDS` (900), `SUBTERRA_TRUST_PROXY_HEADERS` (off).

## Password reset

```
POST /api/auth/forgot-password   { email }        → always the same 200
POST /api/auth/reset-password    { token, password, password_confirmation }
```

There is no `GET` that validates or consumes a token: a link scanner or a
browser prefetch would spend it before the user ever saw the page.

| | |
|---|---|
| **Token** | 256 bits from `secrets.token_urlsafe` — never `random` |
| **Storage** | `password_reset_tokens`, SHA-256 hash only; the raw token exists in the emailed link and nowhere else |
| **Expiry** | 30 minutes, `SUBTERRA_PASSWORD_RESET_TTL_SECONDS` |
| **Consumption** | one atomic `UPDATE … WHERE used_at IS NULL AND expires_at > now RETURNING user_id` |
| **After success** | password rehashed with the existing PBKDF2 implementation; **all sessions revoked** |

**One answer for every input.** `forgot-password` returns the same status and
body for a registered address, an unknown one, a malformed one, a throttled one,
and one whose email failed to send. Any difference is an account-existence
oracle, and the endpoint is unauthenticated so anyone may ask it anything.

**One answer for every bad token.** Missing, malformed, expired, already used —
all give *"This password reset link is invalid or has expired."* Telling them
apart tells an attacker which guesses were close. Password-validation errors
*are* shown plainly: they concern the user's own input and leak nothing. The
password is validated **before** the token is consumed, so a mistyped password
does not burn the link.

**Consumption is atomic.** The `WHERE` clause is the check and the `SET` is the
consumption, in one statement. The obvious three-step version — read, change
password, mark used — has a window in which a second request reads the same
unused token; two clicks on a slow connection are enough. A test races six
threads at one token and asserts exactly one succeeds.

**Sessions are revoked** on success. A reset usually means the password was lost
or is believed compromised; sessions surviving it would preserve exactly the
access it is meant to remove. The **account** failed-login counter is cleared
too, but the **per-address** one deliberately is not — clearing it would let an
attacker refill the budget they spent guessing at other accounts by resetting a
password on one they own.

### Email delivery

`auth/mailer.py` defines one interface — `send_password_reset(email,
reset_url)` — and the password-reset service holds nothing else. It cannot tell
which provider is installed, and must not be able to.

```
PasswordResetService
        │
        ▼
PasswordResetMailer                          selected by SUBTERRA_EMAIL_PROVIDER
        ├── ConsoleMailer        console  ·  development: writes the link to the log
        ├── ResendMailer         resend   ·  production: one HTTPS POST to Resend
        ├── CapturingMailer          —    ·  tests: in memory, never selectable
        └── UnconfiguredMailer       —    ·  nothing chosen: raises
```

**Selection is explicit and never falls back.** `SUBTERRA_EMAIL_PROVIDER=resend`
without `RESEND_API_KEY` or `SUBTERRA_EMAIL_FROM` fails at **startup**. It does
not quietly become console delivery — that deployment would look healthy while
writing every live reset token into its own log. It does not defer the failure
to send time either: `forgot-password` answers identically whether or not the
mail went out, so a send-time failure is invisible to everyone except whoever
eventually reads the log. Startup is the only moment where it can be loud.
`ConsoleMailer` is likewise **refused** when `SUBTERRA_ENV` is not a development
value, for the same reason.

Either way the API answer is unchanged, so a delivery failure is not an oracle.
Loud internally, silent externally — those live in different places and do not
conflict.

#### Resend

One HTTPS POST to `https://api.resend.com/emails` with a bearer token and a JSON
body (`from`, `to`, `subject`, `html`, `text`, optional `reply_to`).

**No SDK, and no new dependency.** `requests` is already a direct dependency
(`ingestion/sources.py`, `ingestion/downloader.py`). A provider SDK would buy
convenience with a supply-chain surface, a release cadence and a second HTTP
stack, for a request that fits on a screen.

| Failure | Result |
|---|---|
| 4xx / 5xx | `EmailDeliveryError`, status code + a short scrubbed reason |
| timeout / connection refused / TLS | `EmailDeliveryError` |
| 2xx whose body is unreadable or has no `id` | `EmailDeliveryError` — *"probably accepted" is not accepted* |

**No retries.** Not "bounded retries" — none. This runs synchronously inside a
request someone is waiting on, so a retry mostly makes the failure twice as
slow, and a 429 answered by asking again immediately is the one response
guaranteed not to help. The user's retry is requesting another link, which is
one click and already rate-limited. Background delivery would mean persisting a
live credential into a job record — a worse trade than a synchronous failure.

**Secrets never travel with errors.** The API key and the reset URL are scrubbed
out of any provider text before it reaches an exception message, because that
message becomes a log line. Scrubbing happens *before* truncation, so a secret
cannot survive by being cut in half. The provider's `request_id` and full body
are never reproduced.

#### The reset link

Built from `SUBTERRA_APP_URL` and the token, and from nothing else — in
particular **never from the request `Host` header**, which is the standard route
to a poisoned reset link: the attacker's host arrives in a header, is baked into
an email we send, and the victim clicks it. `reset_url(token)` is not given the
request at all, so there is no header to trust or distrust. A non-absolute
`SUBTERRA_APP_URL` is refused at import.

The email carries the token (it must — it is the link), and carries nothing
else: no password, no hash, no session token, no token hash, no user id, no
database id, no diagnostics. It loads nothing from the network — no logo file,
no web font, no tracking pixel — so there is nothing to block and nothing that
reports it was opened. The copy says *someone* asked, never *you* asked; nobody
knows who typed the address.

**To add another provider:** implement the one method and give it a name in
`configure_from_environment`. Nothing else changes.

#### Configuration

| Variable | Required | Meaning |
|---|---|---|
| `SUBTERRA_EMAIL_PROVIDER` | — | `console` or `resend`. Unset = console in development, nothing in production. |
| `SUBTERRA_ENV` | — | `development`/`dev`/`test`/`local` permit console delivery. Anything else does not. |
| `SUBTERRA_APP_URL` | — | Base of the emailed link. Default `http://localhost:3000`. Must be absolute. |
| `RESEND_API_KEY` | with `resend` | From <https://resend.com/api-keys>. Never committed. |
| `SUBTERRA_EMAIL_FROM` | with `resend` | e.g. `Subterra AI <no-reply@mail.example.com>` |
| `SUBTERRA_EMAIL_REPLY_TO` | no | Where replies go, if anywhere. |
| `SUBTERRA_EMAIL_TIMEOUT_SECONDS` | no | Default 10, max 60. |
| `SUBTERRA_PASSWORD_RESET_TTL_SECONDS` | no | Default 1800. The email quotes whatever this says. |

`SUBTERRA_APP_BASE_URL` is still read as a fallback so an existing deployment
does not break on upgrade; `SUBTERRA_APP_URL` is the documented name.

Placeholders live in `.env.example`; `.env` is git-ignored and must stay that
way. Nothing prints a key: a missing one is reported **by variable name only**.

**Local development** — nothing to set. The API selects `ConsoleMailer` and
writes the link to the log:

```
docker compose logs api | grep reset-password
```

**Production**

```bash
SUBTERRA_ENV=production
SUBTERRA_EMAIL_PROVIDER=resend
SUBTERRA_APP_URL=https://app.example.com
RESEND_API_KEY=…                       # from the Resend dashboard
SUBTERRA_EMAIL_FROM="Subterra AI <no-reply@mail.example.com>"
```

**Testing without sending real email** — three ways, none of which touches the
network. `CapturingMailer` holds messages in memory for the flow tests;
`ResendMailer(transport=…)` takes an injected transport, so every provider
branch (4xx, 5xx, timeout, refused connection, unreadable body) is exercised
without a key or a socket; and `tests/test_email_provider.py` sabotages
`requests.post` to prove the injection is real rather than decorative. No test
needs a Resend account, and CI does not have one.

#### Before this delivers anything in production

**The sending domain must be added and verified in Resend first** — SPF and
DKIM records published, domain showing verified in the dashboard. Until then
Resend rejects the send, or the message is delivered and filtered as spam. That
is a DNS and dashboard task, not a code one, and nothing in this repository can
do it or check it.

**Three different things, routinely confused:**

| | What it means |
|---|---|
| **API accepted** | Resend returned 2xx with an id. All this code can observe. |
| **Provider delivered** | Resend handed the message to the recipient's mail server. Visible only in the Resend dashboard. |
| **Recipient received it** | It reached an inbox rather than a spam folder. Not observable from here at all. |

The log line says *accepted by provider*, and deliberately not *sent*. A green
API response is not evidence that anybody got an email, and this integration
should not be described as production-ready on the strength of one.

**No delivery webhooks.** The reset flow does not need them: it already treats
non-delivery correctly by failing loudly on the server and saying nothing
different to the caller. Bounce and complaint handling is worth adding when
there is a reason to act on it, and is not part of this.

### Abuse control

Separate policy, same PostgreSQL mechanism as the login limiter: 3 requests per
address and 10 per client IP, per hour (`SUBTERRA_RESET_EMAIL_MAX`,
`SUBTERRA_RESET_IP_MAX`, `SUBTERRA_RESET_WINDOW_SECONDS`). A throttled caller
still receives the **generic acknowledgement** — a 429 here would say "this
address was worth throttling". The login limiter's own budgets are untouched.

## Not done here

No email verification, no social login, no MFA, and no roles
or permissions beyond owner/system. Registration is deliberately **not** rate
limited: credential guessing was the threat being addressed, and account-creation
spam is a separate decision.
