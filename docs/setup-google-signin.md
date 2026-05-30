# Setup — Google Sign In

Lets office staff log in with their Google Workspace / Gmail account instead
of (or alongside) the shared dashboard password. Coexists with the password
flow — password keeps working; Google is an extra button.

## When to use

- You don't want to share a password across the office (each person uses their own Google account).
- You want to revoke access by simply removing an email from the allow list (no need to rotate a password).
- You're running the public demo at `inmo-demo.ekoaiautomation.com` and want to gate it to specific Google accounts.

## 1. Create the Google OAuth client

1. Open https://console.cloud.google.com.
2. Top bar → pick (or create) a project (e.g. `eko-ai-realtors-demo`).
3. **APIs & Services → OAuth consent screen** → External → fill App name / support email → Save and continue. You can keep it in "Testing" mode while only your own accounts use it.
4. **APIs & Services → Credentials → + Create credentials → OAuth client ID**.
5. Application type: **Web application**.
6. **Authorized JavaScript origins** — add every URL where the dashboard runs:
   - `http://localhost:3004` (local dev)
   - `https://inmo-demo.ekoaiautomation.com` (demo)
   - `https://<your-customer-domain>` (each pilot install)
7. **Authorized redirect URIs** — add the backend callback for **every** origin above
   (the "Sign in with Google" button uses `ux_mode=redirect`, which is reliable on mobile;
   popup mode opens a blank tab on phones):
   - `http://localhost:3004/api/v1/auth/login/google/callback` (local dev)
   - `https://inmo-demo.ekoaiautomation.com/api/v1/auth/login/google/callback` (demo)
   - `https://<your-customer-domain>/api/v1/auth/login/google/callback` (each pilot install)

   Google redirects the browser (top-level POST) to this URL with the signed ID token; the
   backend (`POST /api/v1/auth/login/google/callback`) verifies the double-submit CSRF token +
   the ID token, sets the session cookie, and 303-redirects into `/leads`.
8. Create → copy the **Client ID** (looks like `1234567890-xxxxxx.apps.googleusercontent.com`).

## 2. Wire the .env

```env
# Backend — validates the ID token
GOOGLE_CLIENT_ID=1234567890-xxxxxx.apps.googleusercontent.com

# Bootstrap admin(s): pinned in env, ALWAYS admin, can't be removed/demoted from
# the UI (lockout-proof). Comma-separated. Set at least one before turning on auth.
GOOGLE_ADMIN_EMAILS=you@gmail.com

# Optional static members via env (back-compat). Most access is managed in the UI.
GOOGLE_ALLOWED_EMAILS=
GOOGLE_ALLOWED_DOMAIN=

# Frontend — same client ID, exposed via NEXT_PUBLIC_*
NEXT_PUBLIC_GOOGLE_CLIENT_ID=1234567890-xxxxxx.apps.googleusercontent.com
```

**Access model.** The list of who may sign in lives in the database (table
`allowed_users`) and is managed by admins in **Settings → Team**. The env vars are
the bootstrap + back-compat layer. Resolution precedence for a verified email:

1. `GOOGLE_ADMIN_EMAILS` (env) → **admin**, immutable (seeded into the table on startup);
2. `allowed_users` row → its role (`admin` | `member`);
3. `GOOGLE_ALLOWED_EMAILS` (env) → member;
4. `GOOGLE_ALLOWED_DOMAIN` (env) → member (any `@domain`);
5. otherwise → **denied** (safe default — no accidental open access).

**Roles.** `admin` can manage the team + branding (the whole Settings page).
`member` can use the dashboard but not Settings (hidden in the nav; the API returns
403). The shared `DASHBOARD_PASSWORD` always signs in as **admin** (master key).

## 3. Restart + verify

```bash
docker compose restart eko-realestate-backend eko-realestate-frontend
```

Open `/login` — you should see the **"Sign in with Google"** button below the
password box. The button renders when `GOOGLE_CLIENT_ID` + `NEXT_PUBLIC_GOOGLE_CLIENT_ID`
are set and at least one of (`GOOGLE_ADMIN_EMAILS`, `GOOGLE_ALLOWED_EMAILS`,
`GOOGLE_ALLOWED_DOMAIN`) is non-empty. `GET /api/v1/auth/me` returns
`{"google_signin_enabled": …, "role": …}` to debug from the network tab.

Sign in as a bootstrap admin, open **Settings → Team**, and add the rest of the
office (each as admin or member) — no redeploy needed.

## 4. How it works (one paragraph)

1. User clicks "Sign in with Google" → with `ux_mode=redirect`, Google does a top-level
   navigation (no popup) and, after the account is chosen, **POSTs** the signed **ID token**
   (JWT) plus a `g_csrf_token` to `POST /api/v1/auth/login/google/callback`.
2. Backend verifies the double-submit CSRF token (body `g_csrf_token` == cookie `g_csrf_token`),
   then validates the ID token signature against Google's public keys (`google-auth`) AND
   `aud == GOOGLE_CLIENT_ID` AND `email_verified == true`.
3. Backend resolves the verified email against the access list (above) to a role; if denied it
   303-redirects to `/login?error=google_denied` (invalid token/CSRF → `?error=google_failed`).
4. On success it issues the **same HMAC-signed `eko_auth` cookie** as the password flow — but the
   token now carries the email + role, which gates the admin-only Settings/Team APIs — and
   303-redirects into `/leads`.

> Why redirect, not popup: mobile browsers open the GIS popup as a separate tab, so the
> credential never returns to the original tab and you get a blank `accounts.google.com/gsi/transform`
> page. The redirect flow works the same on phones and desktops. (The legacy JSON popup endpoint
> `POST /api/v1/auth/login/google` is kept for back-compat but the button no longer uses it.)

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Button not visible | `GOOGLE_CLIENT_ID` empty, or no admin/allow env set | Set `GOOGLE_CLIENT_ID` + `GOOGLE_ADMIN_EMAILS` + `NEXT_PUBLIC_GOOGLE_CLIENT_ID`, restart |
| Popup opens then closes immediately | Origin not in "Authorized JavaScript origins" | Add the URL in Google Console, wait ~5 min |
| Blank `accounts.google.com/gsi/transform` tab (esp. mobile) | Callback URL not in "Authorized redirect URIs" | Add `…/api/v1/auth/login/google/callback` for that origin, wait ~5 min |
| Lands on `/login?error=google_failed` | CSRF/token rejected (often a stale redirect URI or `aud` mismatch) | Confirm the redirect URI + that `GOOGLE_CLIENT_ID` matches the built `NEXT_PUBLIC_GOOGLE_CLIENT_ID` |
| 401 `email_not_in_allow_list` | Account not on the list | Add it in Settings → Team (or to `GOOGLE_ADMIN_EMAILS`) |
| Logged in but no Settings tab | You're a `member`, not `admin` | Have an admin promote you in Settings → Team |
| 401 `invalid_id_token: Token used too late` | Server clock skew | `sudo ntpdate -s pool.ntp.org` on the ROG |
| `email_not_verified` | Account is a Workspace alias not yet verified | Use a verified primary email |

## 6. Security notes

- The ID token is verified server-side every login — the client can't lie about which Google account it represents.
- The session token carries the email + role; admin-only routes (`/api/v1/settings`, `/api/v1/team`) enforce `require_admin` server-side, so hiding the nav link is defense-in-depth, not the gate.
- Rotating someone out = remove them in Settings → Team (no restart). They lose access on the next session check (sessions also expire after `AUTH_TTL_HOURS`, default 7 days; `POST /api/v1/auth/logout` or a backend restart kills them sooner).
- Lockout-proofing: `GOOGLE_ADMIN_EMAILS` admins can't be removed/demoted from the UI, the API refuses to remove the **last** admin, and the password always works as admin.
- The password flow is **not** disabled by enabling Google. To run Google-only, set `DASHBOARD_PASSWORD` to a random 64-char string nobody knows.
