export const CURRENT_VERSION = "0.0.1";

export interface VersionEntry {
  version: string;
  date: string;
  title: string;
  changes: string[];
}

export const CHANGELOG: VersionEntry[] = [
  {
    version: "0.0.1",
    date: "2026-05-25",
    title: "Bootstrap",
    changes: [
      "Repo skeleton: FastAPI backend + Next.js frontend + Postgres + Redis + Ollama via docker-compose.",
      "Health endpoint at GET /api/v1/health.",
      "Landing placeholder with brand-aligned design (Eko AI violet palette).",
      "README + roadmap + architecture docs.",
    ],
  },
];
