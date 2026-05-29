# Connecting real email (Resend)

Eko AI Realtors speaks email through **Resend**. In dev the email channel runs
SIMULATED (outbound is logged, the inbound webhook accepts unsigned requests), so
it works end to end with no account. This guide wires real email for the demo /
a pilot.

> ## ⚠️ Isolation from Eko AI Main (non-negotiable)
>
> Eko AI Main (the sales platform) already has a verified Resend domain
> `biz.ekoaiautomation.com` with its own API key + inbound webhook. Eko AI
> Realtors is a **separate product** and MUST use its **own dedicated subdomain**
> (e.g. `realtors.ekoaiautomation.com`), its **own API key**, and its **own
> webhook secret**. NEVER reuse `biz.*`, the sales-platform key, or its webhook.
> They share the same Resend account and the same Cloudflare zone
> (`ekoaiautomation.com`), but the subdomain + credentials are isolated so a
> change here can never affect the sales platform.

## 1. Add a dedicated sending domain in Resend

In the [Resend dashboard](https://resend.com) → **Domains → Add Domain**:

- Domain: **`realtors.ekoaiautomation.com`** (a subdomain — distinct from `biz.*`).
- Region: keep the same region as the account (the demo uses `us-east-1`).

Resend shows the DNS records to add. For a subdomain you get:

| Type | Name (host) | Value | Purpose |
|---|---|---|---|
| TXT | `realtors` | `v=spf1 include:_spf.resend.com ~all` | SPF (sender authorization) |
| TXT | `resend._domainkey.realtors` | `p=MIG…` (long key Resend gives you) | DKIM (signature) |
| MX | `send.realtors` | `feedback-smtp.us-east-1.amazonses.com` (prio 10) | bounce/complaint (MAIL FROM) |
| TXT | `send.realtors` | `v=spf1 include:amazonses.com ~all` | MAIL FROM SPF |
| TXT | `_dmarc.realtors` | `v=DMARC1; p=none;` | DMARC (optional but recommended) |

**For two-way email** (the lead replies and the agent continues the thread) also
add the **inbound** MX record Resend gives you for receiving:

| Type | Name (host) | Value | Purpose |
|---|---|---|---|
| MX | `realtors` | `inbound-smtp.us-east-1.amazonaws.com` (prio 10) | inbound receiving |

> Outbound-only (the agent emails the lead, replies go elsewhere) needs just
> SPF + DKIM. Add the inbound MX only if you want replies to flow back into the
> dashboard via the webhook.

## 2. Add the records in Cloudflare

Cloudflare zone `ekoaiautomation.com` (same zone as the rest of the demo). For
each record above: **DNS → Records → Add record**, type/name/value as shown,
**Proxy status = DNS only** (grey cloud — never proxy mail records). Wait for
propagation, then click **Verify** in Resend until the domain shows *Verified*.

## 3. Create a dedicated API key + inbound webhook

- **API key**: Resend → **API Keys → Create** → name it `eko-ai-realtors` →
  scope **Sending access** (add **Full access** only if you manage domains via
  API). Copy the `re_…` value — this is `RESEND_API_KEY`. (Do NOT reuse the
  sales-platform key.)
- **Inbound webhook** (only if you added the inbound MX): Resend → **Webhooks →
  Add** → endpoint
  `https://inmo-demo.ekoaiautomation.com/api/v1/webhooks/email` → subscribe to
  **`email.received`**. Copy the signing secret (`whsec_…`) — this is
  `RESEND_WEBHOOK_SECRET`.

## 4. Configure `.env` (on the ROG, Realtors stack only)

In the Realtors `.env` (gitignored; never commit these):

```bash
EMAIL_SIMULATED=false
RESEND_API_KEY=re_xxxxxxxxxxxxxxxxxxxxxxxx              # Realtors' OWN key
RESEND_FROM=Eko AI Realtors <noreply@realtors.ekoaiautomation.com>
RESEND_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxxxxxxxxx        # only if inbound is enabled
```

Then rebuild + recreate **only** the Realtors backend:

```bash
docker compose build backend && docker compose up -d backend
```

(`docker-compose.yml` already passes `EMAIL_SIMULATED` / `RESEND_API_KEY` /
`RESEND_FROM` / `RESEND_WEBHOOK_SECRET` to `eko-realestate-backend`.)

## 5. Test the round trip

Create a lead with your own email + a first message (Add Lead → channel **Email**),
or send a test inbound. Expected:

1. The agent's reply is emailed from `noreply@realtors.ekoaiautomation.com`.
2. (Two-way) Replying to it hits `/api/v1/webhooks/email`; the backend validates
   the Svix signature, appends the message to the lead's email conversation, and
   the AI continues the thread.
3. The conversation shows in the dashboard `/leads/{id}`.

Watch it happen:

```bash
docker compose logs -f backend | grep -iE "email|resend|turn done"
```

## How it works (for reference)

- **Outbound**: `app/services/email.py::send_email` POSTs to
  `https://api.resend.com/emails` (Bearer `RESEND_API_KEY`). Threading via
  `In-Reply-To` + `References` headers. SIMULATED mode logs instead.
- **Inbound**: `app/api/v1/webhooks/email.py` (`POST /api/v1/webhooks/email`)
  verifies the Svix signature (`verify_resend_signature`, skipped when SIMULATED),
  parses the `email.received` payload (`parse_inbound_email`), and hands a
  `ParsedMessage(channel="email")` to the orchestrator — same path as SMS/WhatsApp.
- **Idempotency**: the UNIQUE constraint on `messages.external_id` (RFC822
  Message-ID) dedupes provider retries.

## Cost & safety notes

- Resend's free tier covers a pilot; outbound is billed per email beyond it.
- A public inbound webhook means anyone who emails the address triggers the agent
  (an LLM call + an outbound email). For a public demo, prefer SIMULATED or
  outbound-only (no inbound MX); enable full two-way on the customer's install.
- Keep `EMAIL_SIMULATED=false` only where `RESEND_API_KEY` is set — `send_email`
  raises a clear error if it runs real without a key.
