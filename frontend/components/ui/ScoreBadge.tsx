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
const TIER_LABEL: Record<ScoreTier, string> = { hot: "Caliente", warm: "Tibio", cold: "Frío" };

export function ScoreBadge({
  score,
  showLabel = false,
  size = "sm",
}: {
  score: number;
  showLabel?: boolean;
  size?: "sm" | "lg";
}) {
  const tier = tierFor(score);
  const pad = size === "lg" ? "px-2.5 py-1 text-sm" : "px-1.5 py-0.5 text-[11px]";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md border font-semibold tabular-nums ${pad} ${TIER_STYLE[tier]}`}
      title={`Score ${score}/100 · ${TIER_LABEL[tier]}`}
    >
      <span aria-hidden>{TIER_ICON[tier]}</span>
      {score}
      {showLabel && <span className="font-normal opacity-80">· {TIER_LABEL[tier]}</span>}
    </span>
  );
}
