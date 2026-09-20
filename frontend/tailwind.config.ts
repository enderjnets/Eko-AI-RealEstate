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
        // v4 additions: the tinted section grounds and the dark consult panel.
        "ln-stone": "#DCD7CE",
        "ln-dark": "#2A2723",
        "ln-cream": "#F7F4ED",
        "ln-gold": "#8A7A5E",
        "ln-hair": "#DCD5C6",
        // v6: the ground under the pinned hero film.
        "ln-night": "#0F0E0C",

        // The Journal ("jr-"). A third prefix rather than reusing "ln-",
        // for the reason written above one level down: five of these match an
        // "ln-" exactly, but six are only NEARLY the same — `ln-muted #8A8172`
        // against this palette's faint #8A8272 is one hex digit, `ln-dark
        // #2A2723` against the strip border #2A2621 is two. Borrowing a near
        // match is a fidelity break nobody can see in review, and a later
        // restyle of the landing page would silently move the article.
        "jr-noir": "#0F0E0C",
        "jr-ink": "#242219",
        "jr-cream": "#F4F1EA",
        "jr-warm": "#FBF9F4",
        "jr-offwhite": "#F7F4ED",
        "jr-body": "#333333",
        "jr-body-muted": "#4A463D",
        "jr-secondary": "#57534A",
        "jr-faint": "#8A8272",
        "jr-brass": "#8A7A5E",
        "jr-brass-light": "#C6B48C",
        "jr-rule": "#DCD5C6",
        "jr-rule-strong": "#C6BEAD",
        "jr-photo": "#E5DFD2",
        "jr-strip-border": "#2A2621",
        "jr-strip-fill": "#181613",
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
