"use client";

/**
 * Cloudflare Turnstile for the public capture form.
 *
 * This exists because the backend half shipped without it. `TURNSTILE_SECRET`
 * made verification mandatory and fail-closed, `.env.example` said "set BOTH or
 * NEITHER" — and there was no widget to set, so following that instruction made
 * every real submission fail with `captcha_failed`. The one defence the docs
 * call "the only one a determined script cannot outspend" could not be turned
 * on.
 *
 * Renders nothing at all when no site key is configured, which is the correct
 * default: an install with no Cloudflare account still gets the honeypot, the
 * per-IP budget and the global ceiling.
 */

import { useEffect, useRef } from "react";

declare global {
  interface Window {
    turnstile?: {
      render: (
        el: HTMLElement,
        opts: {
          sitekey: string;
          callback: (token: string) => void;
          "expired-callback"?: () => void;
          "error-callback"?: () => void;
          theme?: "light" | "dark" | "auto";
        },
      ) => string;
      remove: (id: string) => void;
    };
  }
}

const SCRIPT_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";

let scriptPromise: Promise<void> | null = null;

function loadScript(): Promise<void> {
  // Module-level so React 18's double-invoked effects in development, and two
  // widgets on one page, share a single load instead of racing.
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise<void>((resolve, reject) => {
    if (typeof document === "undefined") return resolve();
    if (window.turnstile) return resolve();
    const el = document.createElement("script");
    el.src = SCRIPT_SRC;
    el.async = true;
    el.defer = true;
    el.onload = () => resolve();
    el.onerror = () => {
      // Let the next mount try again rather than caching a dead promise.
      scriptPromise = null;
      reject(new Error("turnstile script failed to load"));
    };
    document.head.appendChild(el);
  });
  return scriptPromise;
}

export const TURNSTILE_SITE_KEY =
  process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY || "";

export function Turnstile({
  onToken,
  onError,
}: {
  onToken: (token: string | null) => void;
  onError?: () => void;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  // Keep the callbacks in refs: passing them to Turnstile's imperative render
  // captures them once, and a re-render with a new closure would otherwise
  // deliver the token to a function nobody is listening to any more.
  const onTokenRef = useRef(onToken);
  const onErrorRef = useRef(onError);
  onTokenRef.current = onToken;
  onErrorRef.current = onError;

  useEffect(() => {
    if (!TURNSTILE_SITE_KEY || !holder.current) return;
    let widgetId: string | null = null;
    let cancelled = false;

    loadScript()
      .then(() => {
        if (cancelled || !holder.current || !window.turnstile) return;
        widgetId = window.turnstile.render(holder.current, {
          sitekey: TURNSTILE_SITE_KEY,
          theme: "auto",
          callback: (token) => onTokenRef.current(token),
          // A token is single-use and short-lived. Clearing it on expiry means
          // a form left open for ten minutes asks for a fresh challenge rather
          // than submitting a token the server will reject.
          "expired-callback": () => onTokenRef.current(null),
          "error-callback": () => {
            onTokenRef.current(null);
            onErrorRef.current?.();
          },
        });
      })
      .catch(() => {
        onTokenRef.current(null);
        onErrorRef.current?.();
      });

    return () => {
      cancelled = true;
      if (widgetId && window.turnstile) window.turnstile.remove(widgetId);
    };
  }, []);

  if (!TURNSTILE_SITE_KEY) return null;
  return <div ref={holder} className="flex justify-center" />;
}
