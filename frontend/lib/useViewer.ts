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
