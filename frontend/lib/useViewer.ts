"use client";

import { useEffect, useState } from "react";
import { authApi } from "@/lib/api";

/**
 * True when the current session is a read-only "viewer" (self-registered demo
 * account). Write controls hide themselves for viewers; the backend also rejects
 * any write from a viewer (403) as the real guarantee.
 */
export function useViewer(): boolean {
  const [isViewer, setIsViewer] = useState(false);
  useEffect(() => {
    authApi
      .me()
      .then((m) => setIsViewer(Boolean(m.auth_enabled) && m.role === "viewer"))
      .catch(() => {});
  }, []);
  return isViewer;
}

/**
 * True when the session runs the platform rather than an agency.
 *
 * Controls that spend something shared between every agency — the MLS sync,
 * discovery — are operator-only in the backend. Without this the button was
 * still rendered for everyone and the empty state told them to press it, so a
 * tenant's only path forward was an unexplained 403.
 */
export function usePlatformOperator(): boolean {
  const [isOperator, setIsOperator] = useState(false);
  useEffect(() => {
    authApi
      .me()
      .then((m) => setIsOperator(Boolean(m.is_platform_operator)))
      .catch(() => {});
  }, []);
  return isOperator;
}

/**
 * True when the session may open Settings.
 *
 * `SettingsContent` bounces non-admins to /leads and the settings API is behind
 * `require_admin`, so a "fix it in Settings" link shown to a member is a link
 * into a wall. Every other Settings entry point in the app is already gated on
 * this; the Content page's was not.
 */
export function useSettingsAccess(): boolean {
  const [canOpen, setCanOpen] = useState(false);
  useEffect(() => {
    authApi
      .me()
      // Auth off (dev / single-customer demo) means everyone is an admin,
      // which is how the rest of the app reads it too.
      .then((m) => setCanOpen(!m.auth_enabled || m.role === "admin"))
      .catch(() => {});
  }, []);
  return canOpen;
}
