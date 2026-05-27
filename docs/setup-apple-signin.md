# Setup — Sign in with Apple

Lets office staff log in with their Apple Account instead of (or alongside) the
shared dashboard password and Google. Coexists with both — password keeps
working, Google keeps working, Apple is an extra button.

It reuses the **same office allow-list as Google** (`GOOGLE_ADMIN_EMAILS` /
`allowed_users` table / `GOOGLE_ALLOWED_EMAILS` / `GOOGLE_ALLOWED_DOMAIN`): the
list is keyed on the email, not on who issued the token. So an email already
allowed for Google logs in via Apple with the same role.

## When to use

- Staff prefer their Apple Account, or you ship a customer install where Apple is expected.
- You want to gate the public demo at `inmo-demo.ekoaiautomation.com` to specific accounts.

> **Apple Private Relay.** Apple lets users hide their email behind a
> `@privaterelay.appleid.com` address. That relay address must be explicitly
> allow-listed (or the user must choose "Share My Email"), otherwise login is
> denied — same as any other unlisted email.

## 1. Create the Apple identifiers

You need an **App ID** (Primary) and a **Services ID** (the web client). Do this
at https://developer.apple.com → Certificates, Identifiers & Profiles.

1. **Identifiers → + → App IDs → App** — create (or reuse) an App ID and enable
   the **Sign in with Apple** capability. This is the "primary" the Services ID
   groups under. (Bundle ID e.g. `com.ekoai.realtors`.)
2. **Identifiers → + → Services IDs** — create one, e.g.
   `com.ekoai.realtors.signin`. **This identifier is your `APPLE_CLIENT_ID`.**
3. Edit the Services ID → enable **Sign in with Apple** → **Configure**:
   - **Primary App ID**: the App ID from step 1.
   - **Domains and Subdomains**: every domain the dashboard runs on, e.g.
     `inmo-demo.ekoaiautomation.com` (no scheme, no path).
   - **Return URLs**: the full HTTPS return URL(s), e.g.
     `https://inmo-demo.ekoaiautomation.com/login`. Apple requires **HTTPS** and
     does **not** accept `localhost` — for local dev use a tunnel
     (`https://<name>.trycloudflare.com/login`) registered here.
   - Save.

> Verifying the **identity token at login does not require** a `.p8` private key,
> Key ID, or Team ID — the web popup flow returns the `id_token` directly and the
> backend verifies its signature against Apple's public keys. You only need those
> extras later for server-to-server features (token refresh / account-deletion
> revocation), which this product does not use yet.

## 2. Wire the .env

```env
# Backend — the Services ID; also the token `aud` the backend validates.
APPLE_CLIENT_ID=com.ekoai.realtors.signin

# Frontend — same Services ID + a registered Return URL. In popup mode the
# return URL's ORIGIN must equal the site origin.
NEXT_PUBLIC_APPLE_CLIENT_ID=com.ekoai.realtors.signin
NEXT_PUBLIC_APPLE_REDIRECT_URI=https://inmo-demo.ekoaiautomation.com/login
```

Access is governed by the **Google allow-list** (see
[`setup-google-signin.md`](setup-google-signin.md) §2). Make sure at least one
`GOOGLE_ADMIN_EMAILS` bootstrap admin (or a DB / domain entry) covers the Apple
email you'll log in with.

## 3. Rebuild + verify

`NEXT_PUBLIC_*` is inlined into the frontend bundle **at build time**, so a
plain restart isn't enough — the frontend image must be rebuilt:

```bash
docker compose build frontend
docker compose up -d backend frontend
```

Open `/login` — you should see the black **"Sign in with Apple"** button below
the password box (under the same "or" divider as Google). It renders when
`NEXT_PUBLIC_APPLE_CLIENT_ID` is set and `GET /api/v1/auth/me` returns
`"apple_signin_enabled": true` (which also needs an allow-list source set).

## 4. How it works (one paragraph)

1. User clicks "Sign in with Apple" → the Apple JS SDK (`appleid.auth.js`) opens a popup (`usePopup: true`); on success the promise resolves in-page with `authorization.id_token` (a signed JWT).
2. Frontend POSTs `{id_token: "..."}` to `POST /api/v1/auth/login/apple`.
3. Backend fetches Apple's public keys (`appleid.apple.com/auth/keys`), matches the token's `kid`, and verifies the **RS256** signature AND `iss == https://appleid.apple.com` AND `aud == APPLE_CLIENT_ID` AND `exp` not passed AND `email_verified`.
4. Backend resolves the verified email against the shared allow-list to a role; if denied → `401 email_not_in_allow_list`.
5. On success it issues the **same HMAC-signed `eko_auth` cookie** as the password/Google flows — the token carries the email + role, which gates the admin-only Settings/Team APIs.

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Button not visible | `NEXT_PUBLIC_APPLE_CLIENT_ID` empty, or no allow-list source set | Set it + an allow-list entry, then **rebuild** the frontend image |
| Popup opens then errors `invalid_client` | Services ID / domain / return URL mismatch | The clientId must be the **Services ID** (not the App ID); the domain + return URL must be registered in its Web Authentication Configuration |
| Popup never resolves | Return URL origin ≠ site origin | In popup mode the return URL origin must equal `window.location.origin`; register the exact site URL |
| 401 `email_not_in_allow_list` | Apple account / relay email not on the list | Add it in Settings → Team (or `GOOGLE_ADMIN_EMAILS`) — for hidden emails add the `@privaterelay.appleid.com` address |
| 401 `invalid_id_token: ... expired` or clock errors | Server clock skew | `sudo ntpdate -s pool.ntp.org` on the ROG |
| `email_not_verified` | Token lacked a verified email | Re-consent choosing "Share My Email"; ensure scope `email` is requested |

## 6. Security notes

- The identity token is verified server-side every login (signature + `iss` + `aud` + `exp`) — the client can't lie about which Apple account it represents.
- The web popup flow uses no client secret / `.p8` key; only the public Services ID is exposed in the bundle.
- The session token carries the email + role; admin-only routes enforce `require_admin` server-side, so hiding the nav link is defense-in-depth, not the gate.
- Rotating someone out = remove them in Settings → Team (no restart). They lose access on the next session check (sessions expire after `AUTH_TTL_HOURS`, default 7 days; logout or a backend restart kills them sooner).
- Enabling Apple does not disable the password or Google flows.
