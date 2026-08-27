FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

FROM node:20-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# Google Sign In client ID — NEXT_PUBLIC_* is inlined at build time.
ARG NEXT_PUBLIC_CANONICAL_URL
ENV NEXT_PUBLIC_CANONICAL_URL=$NEXT_PUBLIC_CANONICAL_URL
ARG NEXT_PUBLIC_GOOGLE_CLIENT_ID
ENV NEXT_PUBLIC_GOOGLE_CLIENT_ID=$NEXT_PUBLIC_GOOGLE_CLIENT_ID
# Sign in with Apple — Services ID + return URL, also inlined at build time.
ARG NEXT_PUBLIC_APPLE_CLIENT_ID
ENV NEXT_PUBLIC_APPLE_CLIENT_ID=$NEXT_PUBLIC_APPLE_CLIENT_ID
ARG NEXT_PUBLIC_APPLE_REDIRECT_URI
ENV NEXT_PUBLIC_APPLE_REDIRECT_URI=$NEXT_PUBLIC_APPLE_REDIRECT_URI
# Public capture form. The form key names the agency in channel_routes; empty
# is correct on a single-agency install. Inlined at build time like the rest —
# an install that sets it only at runtime gets a form that posts no key, which
# is refused the moment a second agency exists.
ARG NEXT_PUBLIC_CAPTURE_FORM_KEY
ENV NEXT_PUBLIC_CAPTURE_FORM_KEY=$NEXT_PUBLIC_CAPTURE_FORM_KEY
# Turnstile's public half. Must be baked in alongside TURNSTILE_SECRET on the
# backend: with the secret set and this empty the server demands a token the
# page cannot produce, and every real submission returns captcha_failed.
ARG NEXT_PUBLIC_TURNSTILE_SITE_KEY
ENV NEXT_PUBLIC_TURNSTILE_SITE_KEY=$NEXT_PUBLIC_TURNSTILE_SITE_KEY
# Public landing content. Every one of these is a factual claim about a real
# brokerage, so an unset value hides its section rather than inventing filler.
# Build-time like the rest: setting them only at runtime leaves the deployed
# page showing the blanks while the .env file looks correctly filled in.
ARG NEXT_PUBLIC_LANDING_ADVISORS
ENV NEXT_PUBLIC_LANDING_ADVISORS=$NEXT_PUBLIC_LANDING_ADVISORS
ARG NEXT_PUBLIC_LANDING_BROKERAGE
ENV NEXT_PUBLIC_LANDING_BROKERAGE=$NEXT_PUBLIC_LANDING_BROKERAGE
ARG NEXT_PUBLIC_LANDING_ADDRESS
ENV NEXT_PUBLIC_LANDING_ADDRESS=$NEXT_PUBLIC_LANDING_ADDRESS
ARG NEXT_PUBLIC_LANDING_PHONE
ENV NEXT_PUBLIC_LANDING_PHONE=$NEXT_PUBLIC_LANDING_PHONE
ARG NEXT_PUBLIC_LANDING_SMS
ENV NEXT_PUBLIC_LANDING_SMS=$NEXT_PUBLIC_LANDING_SMS
ARG NEXT_PUBLIC_LANDING_EMAIL
ENV NEXT_PUBLIC_LANDING_EMAIL=$NEXT_PUBLIC_LANDING_EMAIL
ARG NEXT_PUBLIC_LANDING_YEARS
ENV NEXT_PUBLIC_LANDING_YEARS=$NEXT_PUBLIC_LANDING_YEARS
ARG NEXT_PUBLIC_LANDING_MARKETS
ENV NEXT_PUBLIC_LANDING_MARKETS=$NEXT_PUBLIC_LANDING_MARKETS
ARG NEXT_PUBLIC_LANDING_PORTRAIT
ENV NEXT_PUBLIC_LANDING_PORTRAIT=$NEXT_PUBLIC_LANDING_PORTRAIT
ARG NEXT_PUBLIC_LANDING_BOOKING_URL
ENV NEXT_PUBLIC_LANDING_BOOKING_URL=$NEXT_PUBLIC_LANDING_BOOKING_URL
ARG NEXT_PUBLIC_LANDING_TESTIMONIALS
ENV NEXT_PUBLIC_LANDING_TESTIMONIALS=$NEXT_PUBLIC_LANDING_TESTIMONIALS
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# `public/` is empty today and git does not track empty directories, so a fresh
# clone does not have it — and the runner stage below unconditionally copies it.
# The build therefore worked ONLY on the one machine where somebody had created
# the directory by hand, and failed on every clean checkout, including a
# third-party install (`scripts/install.sh` runs `docker compose build`).
# Measured, not guessed: on a fresh clone the build stopped at
# `failed to compute cache key: "/app/public": not found`.
# Created here rather than committing a `.gitkeep`, so nothing stray ends up
# being served from the site root.
RUN mkdir -p public && npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
EXPOSE 3000
CMD ["npm", "start"]
