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

        // Public landing only ("ln-"). A separate warm palette from the
        // dashboard's cool greys — keeping the prefix means restyling the
        // marketing page can never move a pixel inside the product.
        "ln-paper": "#FBFAF7",
        "ln-canvas": "#F4F1EA",
        "ln-ink": "#17150F",
        "ln-ink-soft": "#3D372C",
        "ln-body": "#57503F",
        "ln-bronze": "#7A5C34",
        "ln-muted": "#8A8172",
        "ln-faint": "#A39A8A",
        "ln-line-strong": "#C9C0AF",
        "ln-line": "#DAD3C6",
        "ln-tint": "#E8E4DC",
      },
      fontFamily: {
        display: ["Inter", "system-ui", "sans-serif"],
        // Namespaced rather than overriding `serif`/`sans`, which would
        // restyle every dashboard page as a side effect.
        "ln-serif": ["var(--font-ln-serif)", "Georgia", "serif"],
        "ln-sans": ["var(--font-ln-sans)", "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};

export default config;
