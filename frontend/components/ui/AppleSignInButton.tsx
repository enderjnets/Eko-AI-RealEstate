"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { authApi } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const APPLE_CLIENT_ID = process.env.NEXT_PUBLIC_APPLE_CLIENT_ID || "";
const APPLE_REDIRECT_URI = process.env.NEXT_PUBLIC_APPLE_REDIRECT_URI || "";
const APPLE_SDK_SRC =
  "https://appleid.cdn-apple.com/appleauth/static/jsapi/appleid/1/en_US/appleid.auth.js";

interface AppleSignInResponse {
  authorization: { code: string; id_token: string; state?: string };
  user?: { email?: string; name?: { firstName?: string; lastName?: string } };
}

declare global {
  interface Window {
    AppleID?: {
      auth: {
        init: (config: Record<string, unknown>) => void;
        signIn: () => Promise<AppleSignInResponse>;
      };
    };
  }
}

function loadAppleScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (typeof window === "undefined") return reject(new Error("no window"));
    if (window.AppleID) return resolve();
    const existing = document.getElementById("apple-signin-sdk") as HTMLScriptElement | null;
    if (existing) {
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error("apple_sdk_failed")));
      return;
    }
    const s = document.createElement("script");
    s.id = "apple-signin-sdk";
    s.src = APPLE_SDK_SRC;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("apple_sdk_failed"));
    document.head.appendChild(s);
  });
}

/**
 * Sign in with Apple JS popup flow: init the SDK with the Services ID, let Apple
 * authenticate in a popup, then POST the returned id_token to the backend (which
 * verifies it and resolves the email against the office allow-list). Mirrors the
 * Google button. Renders nothing if NEXT_PUBLIC_APPLE_CLIENT_ID is unset.
 */
export function AppleSignInButton({ onError }: { onError?: (key: string) => void }) {
  const router = useRouter();
  const { t } = useI18n();
  const [loading, setLoading] = useState(false);
  const ready = useRef(false);

  useEffect(() => {
    if (!APPLE_CLIENT_ID) return;
    let cancelled = false;
    loadAppleScript()
      .then(() => {
        if (cancelled || !window.AppleID) return;
        window.AppleID.auth.init({
          clientId: APPLE_CLIENT_ID,
          scope: "name email",
          // Popup mode resolves the promise in-page; Apple still requires the
          // redirectURI's origin to match window.location.origin and to be a
          // registered return URL in the Services ID config.
          redirectURI: APPLE_REDIRECT_URI || `${window.location.origin}/login`,
          usePopup: true,
        });
        ready.current = true;
      })
      .catch(() => onError?.("auth.appleFailed"));
    return () => {
      cancelled = true;
    };
  }, [onError]);

  const handleClick = useCallback(async () => {
    if (loading || !window.AppleID) return;
    setLoading(true);
    onError?.("");
    try {
      const data = await window.AppleID.auth.signIn();
      const idToken = data?.authorization?.id_token;
      if (!idToken) {
        onError?.("auth.appleFailed");
        setLoading(false);
        return;
      }
      await authApi.loginApple(idToken);
      router.replace("/leads");
    } catch (e) {
      // The SDK rejects with { error: "..." }; a user-cancelled popup is benign.
      const code = (e as { error?: string })?.error || "";
      if (code !== "popup_closed_by_user" && code !== "user_cancelled_authorize") {
        const msg = e instanceof Error ? e.message : "";
        onError?.(msg.includes("not_in_allow_list") ? "auth.appleDenied" : "auth.appleFailed");
      }
      setLoading(false);
    }
  }, [loading, onError, router]);

  if (!APPLE_CLIENT_ID) return null;

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={loading}
      className="w-[280px] inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-black text-white border border-white/20 hover:bg-black/80 disabled:opacity-50 transition-colors"
    >
      {loading ? (
        <Loader2 className="w-4 h-4 animate-spin" />
      ) : (
        <svg aria-hidden="true" viewBox="0 0 384 512" className="w-3.5 h-4 fill-white">
          <path d="M318.7 268.7c-.2-36.7 16.4-64.4 50-84.8-18.8-26.9-47.2-41.7-84.7-44.6-35.5-2.8-74.3 20.7-88.5 20.7-15 0-49.4-19.7-76.4-19.7C73.3 141.2 24 184.9 24 277.6c0 27.2 5 55.3 14.9 84.3 13.3 38.1 61 131.6 110.7 130.1 26-.6 44.4-18.5 78.2-18.5 32.8 0 49.8 18.5 78.5 18.5 50.1-.7 93.3-85.7 106-123.9-67.4-31.8-63.6-93.1-63.6-95.1zm-56.4-216.4C291.5 18.3 286.4 0 286.4 0c-23.1.7-50.5 15.3-66.3 35.9-13.9 18.2-26.7 47.3-23.4 75.4 25.7 2 52.4-13.4 65.6-58.9z" />
        </svg>
      )}
      <span>{loading ? t("auth.appleSigningIn") : t("auth.appleSignIn")}</span>
    </button>
  );
}
