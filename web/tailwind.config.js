/** Brand colors come from CSS variables set at runtime from the active company's config. */
const brand = (name) => `rgb(var(--brand-${name}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: brand("rgb"),
          fg: brand("fg-rgb"),
          soft: brand("soft-rgb"),
          strong: brand("strong-rgb"),
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      keyframes: {
        rowIn: { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
        blink: { "0%, 80%, 100%": { opacity: "0.25" }, "40%": { opacity: "1" } },
      },
      animation: { rowIn: "rowIn 220ms ease-out", blink: "blink 1.2s infinite" },
    },
  },
  plugins: [],
};
