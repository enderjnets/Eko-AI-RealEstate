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
7. **Authorized redirect URIs** — leave **empty**. We use the Google Identity Services "implicit / credential" flow (one-tap + button), not the redirect flow.
8. Create → copy the **Client ID** (looks like `1234567890-xxxxxx.apps.googleusercontent.com`).

## 2. Wire the .env

```env
# Backend — validates the ID token
GOOGLE_CLIENT_ID=1234567890-xxxxxx.apps.googleusercontent.com

# Pick ONE or BOTH allow-list mechanisms (must set at least one).
GOOGLE_ALLOWED_EMAILS=alice@example.com,bob@example.com
GOOGLE_ALLOWED_DOMAIN=ekoaiautomation.com

# Frontend — same client ID, exposed via NEXT_PUBLIC_*
NEXT_PUBLIC_GOOGLE_CLIENT_ID=1234567890-xxxxxx.apps.googleusercontent.com
```

**Safe default**: if both `GOOGLE_ALLOWED_EMAILS` and `GOOGLE_ALLOWED_DOMAIN` are empty, the backend **rejects every Google login** (so we never accidentally let the entire internet into an open dashboard).

## 3. Restart + verify

```bash
docker-compose restart eko-realestate-backend eko-realestate-frontend
```

Open `/login` — you should see the **"Sign in with Google"** button below the password box. The button only renders when:

- `GOOGLE_CLIENT_ID` (backend) is set, AND
- A non-empty allow list (emails or domain) is configured, AND
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID` (frontend) is set.

If you don't see the button, check `GET /api/v1/auth/me` — it returns `{"google_signin_enabled": true|false}` so you can debug from the network tab.

## 4. How it works (one paragraph)

1. User clicks "Sign in with Google" → Google's JavaScript library opens a popup, user picks their Google account.
2. Google returns a signed **ID token** (JWT) to the browser.
3. Frontend POSTs `{id_token: "..."}` to `POST /api/v1/auth/login/google`.
4. Backend validates the token signature against Google's public keys (via `google-auth` library) AND checks `aud == GOOGLE_CLIENT_ID` AND checks `email_verified == true`.
5. Backend checks the verified email against `GOOGLE_ALLOWED_EMAILS` and `GOOGLE_ALLOWED_DOMAIN`. If neither matches → `401`.
6. On success, the backend issues the **same HMAC-signed session cookie** as the password flow (`eko_auth`). No new identity table — Google Sign In is just an alternate way to authenticate, the session model is unchanged.

## 5. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Button not visible | `GOOGLE_CLIENT_ID` empty or allow list empty | Set both env vars, restart |
| Popup opens then closes immediately | Origin not in "Authorized JavaScript origins" | Add the URL in Google Console, wait ~5 min |
| 401 `no_allow_list_configured` | Backend has client ID but no emails/domain | Set `GOOGLE_ALLOWED_EMAILS` or `GOOGLE_ALLOWED_DOMAIN` |
| 401 `email_not_in_allow_list` | Wrong account used | Sign out of that Google account or add it to the allow list |
| 401 `invalid_id_token: Token used too late` | Server clock skew | `sudo ntpdate -s pool.ntp.org` on the ROG |
| `email_not_verified` | Account is a Workspace alias not yet verified | Use a verified primary email |

## 6. Security notes

- The ID token is verified server-side every login — the client can't lie about which Google account it represents.
- We don't store the Google `sub` (subject) anywhere — each login just opens a session for the office. To audit "who logged in", check backend logs for `google_signin_failed reason=...` / successful `set_cookie` events.
- Rotating an employee out = remove their email from `GOOGLE_ALLOWED_EMAILS`, restart backend. They lose access on the next refresh (current sessions die after `AUTH_TTL_HOURS`, default 7 days; restart `eko-realestate-backend` or `POST /api/v1/auth/logout` to kill faster).
- The password flow is **not** disabled by enabling Google. To run Google-only, set `DASHBOARD_PASSWORD` to a random 64-char string nobody knows.
