import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Reuse the Eko AI brand palette for visual consistency across products.
        "eko-noir": "#0B0B0F",
        "eko-violet": "#7C3AED",
        "eko-violet-dark": "#5B21B6",
        "eko-magenta": "#EC4899",
        "eko-green": "#10B981",
      },
      fontFamily: {
        display: ["Inter", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
