# Public demo — `inmo-demo.ekoaiautomation.com`

A live, seeded instance we can show prospects ("here's the product, click around").
Hosted on the ROG, exposed via a **dedicated** Cloudflare Tunnel so it never
touches the sales-platform tunnel (`eko-landing`).

## Safety model

The demo is internet-facing, so it must be harmless to poke at:

- **All channels SIMULATED.** `.env` keeps `WHATSAPP_SIMULATED=true`,
  `EMAIL_SIMULATED=true`, `CALENDAR_SIMULATED=true`. A visitor clicking "send" or
  "book" can never trigger a real WhatsApp message, email, or calendar booking —
  the action is logged, persisted, and reflected in the UI only.
- **Seed data, not real customers.** The demo DB holds the fictional *Sunset
  Realty Group* (Miami) dataset — no real lead PII.
- Optional: put **Cloudflare Access** in front of the hostname for a soft gate
  (email OTP) if you want to limit who sees it.

## One-time setup on the ROG

```bash
# 1. Bring the Realtors stack up with demo data
cd ~/Eko-AI-RealEstate
docker compose up -d
docker compose exec backend alembic upgrade head
docker compose exec backend python scripts/seed_demo.py

# 2. Create a DEDICATED tunnel (do NOT reuse eko-landing)
cloudflared tunnel login
cloudflared tunnel create eko-realtors-demo
cloudflared tunnel route dns eko-realtors-demo inmo-demo.ekoaiautomation.com

# 3. Config from the template, fill the two <PLACEHOLDER> values
cp deploy/cloudflared/config.example.yml ~/.cloudflared/eko-realtors-demo.yml
#   tunnel: <TUNNEL_UUID>           ← from `cloudflared tunnel list`
#   credentials-file: …/<UUID>.json

# 4. Run it (foreground to test)
cloudflared tunnel --config ~/.cloudflared/eko-realtors-demo.yml run
#   then install as a service to survive reboots:
sudo cloudflared --config ~/.cloudflared/eko-realtors-demo.yml service install
```

Verify: `https://inmo-demo.ekoaiautomation.com/leads` shows the seeded leads.

## Alternative: add ingress to the existing `eko-landing` tunnel

If you'd rather not run a second `cloudflared` process, add a hostname to the
sales-platform tunnel's ingress list **above** its `http_status:404` catch-all:

```yaml
  - hostname: inmo-demo.ekoaiautomation.com
    service: http://localhost:3004
```

…then `cloudflared tunnel route dns eko-landing inmo-demo.ekoaiautomation.com`
and restart that tunnel. Trade-off: it couples the demo's availability to the
sales-platform tunnel. The dedicated-tunnel route above keeps them independent
and is preferred.

## Refreshing the demo

The seed is idempotent — re-running wipes the previous demo rows (matched by
`meta.demo = true`) and recreates them:

```bash
docker compose exec backend python scripts/seed_demo.py            # reseed
docker compose exec backend python scripts/seed_demo.py --reset    # wipe only
docker compose exec backend python scripts/seed_demo.py --keep-settings  # keep branding
```

A nightly reset (so visitors always see a clean demo) can be a host cron:

```cron
0 6 * * *  cd /home/enderj/Eko-AI-RealEstate && /usr/bin/docker compose exec -T backend python scripts/seed_demo.py >/dev/null 2>&1
```
