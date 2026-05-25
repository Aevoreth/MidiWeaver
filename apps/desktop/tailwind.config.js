/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--color-bg)",
        surface: "var(--color-surface)",
        panel: "var(--color-panel)",
        border: "var(--color-border)",
        accent: "var(--color-accent)",
        "accent-muted": "var(--color-accent-muted)",
        foreground: "var(--color-text)",
        muted: "var(--color-text-secondary)",
        playhead: "var(--color-playhead)",
        "roll-grid": "var(--color-roll-grid)",
        "roll-note": "var(--color-roll-note)",
        success: "var(--color-success)",
        warning: "var(--color-warning)",
        error: "var(--color-error)",
      },
      fontFamily: {
        sans: ["Segoe UI", "system-ui", "sans-serif"],
        mono: ["Cascadia Code", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
