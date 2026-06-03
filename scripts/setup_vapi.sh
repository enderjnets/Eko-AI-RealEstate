#!/usr/bin/env bash
# Configure the "Eko AI Realtors" VAPI assistant + phone number (idempotent).
#
# Secrets are read from the environment — NOTHING is hardcoded here:
#   VAPI_API_KEY          Bearer for the VAPI REST API
#   VAPI_ASSISTANT_ID     the assistant to configure
#   VAPI_PHONE_NUMBER_ID  (optional) number to route to the assistant
#   VOICE_WEBHOOK_URL     e.g. https://inmo-demo.ekoaiautomation.com/api/v1/webhooks/voice
#   VAPI_WEBHOOK_SECRET   shared secret (must equal the backend's VAPI_WEBHOOK_SECRET)
#
# Usage: VAPI_API_KEY=... VAPI_ASSISTANT_ID=... VOICE_WEBHOOK_URL=... \
#        VAPI_WEBHOOK_SECRET=... [VAPI_PHONE_NUMBER_ID=...] bash scripts/setup_vapi.sh
set -euo pipefail

: "${VAPI_API_KEY:?set VAPI_API_KEY}"
: "${VAPI_ASSISTANT_ID:?set VAPI_ASSISTANT_ID}"
: "${VOICE_WEBHOOK_URL:?set VOICE_WEBHOOK_URL}"
: "${VAPI_WEBHOOK_SECRET:?set VAPI_WEBHOOK_SECRET}"
BASE="${VAPI_BASE_URL:-https://api.vapi.ai}"

read -r -d '' SYSTEM_PROMPT <<'EOF' || true
You are Eko, the friendly AI assistant for a real-estate agency. You answer the
phone, warmly help callers, and qualify them as leads.

PERSONALITY: warm, professional, concise. Speak like a helpful human assistant,
never robotic. Default to ENGLISH; if the caller speaks another language, mirror
it. Do not rush — let the caller finish.

GOAL: figure out what the caller wants and capture the key details, ONE question
at a time:
1) Are they looking to BUY, RENT, or SELL (a valuation)?
2) Which area / neighborhood?
3) Budget range (or, for sellers, the property they want valued).
4) Property type (house, condo, apartment, ...) and bedrooms if relevant.
5) Timeline (how soon are they looking to move / decide?).

BOOKING A VISIT: if the caller wants to see a property or meet, offer to schedule
a visit. Call the `check_availability` tool to read open times, propose one or two,
and once they pick, call `book_visit` with the date/time as ISO-8601 UTC, plus their
phone number and (if known) the property address. Confirm the booked time back to
them clearly.

RULES:
- Only discuss real estate (buying, renting, selling, visits). If asked about
  anything else, politely say you can only help with real-estate inquiries.
- Never invent listings, prices, or availability. If you don't know, say a team
  member will follow up.
- Do not end the call unless the caller is done; close warmly.
EOF

# jq builds valid JSON safely (handles quoting/newlines in the prompt).
PAYLOAD=$(jq -n \
  --arg prompt "$SYSTEM_PROMPT" \
  --arg url "$VOICE_WEBHOOK_URL" \
  --arg secret "$VAPI_WEBHOOK_SECRET" \
  '{
    name: "Eko AI Realtors",
    firstMessage: "Hi, thanks for calling Eko AI Realtors. This is Eko, the assistant. Are you looking to buy, rent, or sell a property today?",
    voice: { provider: "11labs", voiceId: "EXAVITQu4vr4xnSDxMaL", stability: 0.5, similarityBoost: 0.75, useSpeakerBoost: true },
    transcriber: { provider: "deepgram", model: "nova-2", language: "en" },
    server: { url: $url, secret: $secret },
    serverMessages: ["end-of-call-report", "tool-calls", "status-update"],
    analysisPlan: {
      summaryPlan: { enabled: true },
      structuredDataPlan: {
        enabled: true,
        schema: {
          type: "object",
          properties: {
            intent: { type: "string", enum: ["buy", "rent", "valuation", "other"], description: "What the caller wants to do." },
            zone: { type: "string", description: "Neighborhood / area of interest." },
            budget_min: { type: "number", description: "Minimum budget (USD), if mentioned." },
            budget_max: { type: "number", description: "Maximum budget (USD), if mentioned." },
            property_type: { type: "string", description: "house, condo, apartment, ..." },
            timeline: { type: "string", description: "How soon they want to move / decide." },
            name: { type: "string", description: "Caller full name." },
            phone: { type: "string", description: "Callback phone number the caller gave." }
          }
        }
      }
    },
    model: {
      provider: "anthropic",
      model: "claude-sonnet-4-5-20250929",
      messages: [ { role: "system", content: $prompt } ],
      tools: [
        {
          type: "function",
          function: {
            name: "check_availability",
            description: "Return the next available visit time slots.",
            parameters: { type: "object", properties: { days: { type: "integer", description: "How many days ahead to look (default 7)." } } }
          }
        },
        {
          type: "function",
          function: {
            name: "book_visit",
            description: "Book a property visit for the caller.",
            parameters: {
              type: "object",
              properties: {
                datetime: { type: "string", description: "Visit start, ISO-8601 UTC, e.g. 2026-06-10T15:00:00Z." },
                property_address: { type: "string", description: "Address or area of the property to visit." },
                name: { type: "string", description: "Caller full name." },
                phone: { type: "string", description: "Caller phone number in E.164." }
              },
              required: ["datetime"]
            }
          }
        }
      ]
    }
  }')

echo "→ PATCH assistant $VAPI_ASSISTANT_ID"
curl -sS -X PATCH "$BASE/assistant/$VAPI_ASSISTANT_ID" \
  -H "Authorization: Bearer $VAPI_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" | jq '{name, voice: .voice.voiceId, model: .model.model, server: .server.url}'

if [ -n "${VAPI_PHONE_NUMBER_ID:-}" ]; then
  echo "→ PATCH phone number $VAPI_PHONE_NUMBER_ID → assistant + rename"
  curl -sS -X PATCH "$BASE/phone-number/$VAPI_PHONE_NUMBER_ID" \
    -H "Authorization: Bearer $VAPI_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg a "$VAPI_ASSISTANT_ID" '{assistantId: $a, name: "Eko AI Realtors"}')" \
    | jq '{number, name, assistantId}'
fi

echo "✓ done"
