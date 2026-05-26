"use client";

import { useI18n } from "@/lib/i18n";

export type ScoreTier = "hot" | "warm" | "cold";

export function tierFor(score: number): ScoreTier {
  if (score >= 67) return "hot";
  if (score >= 34) return "warm";
  return "cold";
}

const TIER_STYLE: Record<ScoreTier, string> = {
  hot: "bg-red-500/15 text-red-400 border-red-500/30",
  warm: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  cold: "bg-gray-500/15 text-gray-400 border-gray-500/30",
};

const TIER_ICON: Record<ScoreTier, string> = { hot: "🔥", warm: "🟡", cold: "⚪" };

export function ScoreBadge({
  score,
  showLabel = false,
  size = "sm",
}: {
  score: number;
  showLabel?: boolean;
  size?: "sm" | "lg";
}) {
  const { t } = useI18n();
  const tier = tierFor(score);
  const label = t(`score.${tier}`);
  const pad = size === "lg" ? "px-2.5 py-1 text-sm" : "px-1.5 py-0.5 text-[11px]";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border font-semibold tabular-nums ${pad} ${TIER_STYLE[tier]}`}
      title={`Score ${score}/100 · ${label}`}
    >
      <span aria-hidden>{TIER_ICON[tier]}</span>
      {score}
      {showLabel && <span className="font-normal opacity-80">· {label}</span>}
    </span>
  );
}
