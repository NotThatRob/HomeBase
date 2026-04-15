const colors = {
  "error": "var(--color-error)",
  "tertiary-dim": "var(--color-tertiary-dim)",
  "primary-dim": "var(--color-primary-dim)",
  "secondary": "var(--color-secondary)",
  "secondary-fixed": "var(--color-secondary-fixed)",
  "tertiary": "var(--color-tertiary)",
  "error-dim": "var(--color-error-dim)",
  "inverse-primary": "var(--color-inverse-primary)",
  "surface-bright": "var(--color-surface-bright)",
  "on-primary": "var(--color-on-primary)",
  "secondary-fixed-dim": "var(--color-secondary-fixed-dim)",
  "inverse-surface": "var(--color-inverse-surface)",
  "surface-container": "var(--color-surface-container)",
  "secondary-dim": "var(--color-secondary-dim)",
  "surface-tint": "var(--color-surface-tint)",
  "primary-container": "var(--color-primary-container)",
  "on-tertiary-container": "var(--color-on-tertiary-container)",
  "secondary-container": "var(--color-secondary-container)",
  "outline": "var(--color-outline)",
  "primary-fixed-dim": "var(--color-primary-fixed-dim)",
  "surface-container-low": "var(--color-surface-container-low)",
  "on-surface-variant": "var(--color-on-surface-variant)",
  "on-tertiary": "var(--color-on-tertiary)",
  "on-secondary": "var(--color-on-secondary)",
  "primary": "var(--color-primary)",
  "surface-container-high": "var(--color-surface-container-high)",
  "primary-fixed": "var(--color-primary-fixed)",
  "surface-container-lowest": "var(--color-surface-container-lowest)",
  "tertiary-container": "var(--color-tertiary-container)",
  "on-tertiary-fixed-variant": "var(--color-on-tertiary-fixed-variant)",
  "on-error": "var(--color-on-error)",
  "outline-variant": "var(--color-outline-variant)",
  "surface-container-highest": "var(--color-surface-container-highest)",
  "on-secondary-fixed": "var(--color-on-secondary-fixed)",
  "on-error-container": "var(--color-on-error-container)",
  "tertiary-fixed-dim": "var(--color-tertiary-fixed-dim)",
  "on-background": "var(--color-on-background)",
  "tertiary-fixed": "var(--color-tertiary-fixed)",
  "surface-variant": "var(--color-surface-variant)",
  "surface-dim": "var(--color-surface-dim)",
  "on-secondary-container": "var(--color-on-secondary-container)",
  "error-container": "var(--color-error-container)",
  "on-secondary-fixed-variant": "var(--color-on-secondary-fixed-variant)",
  "on-tertiary-fixed": "var(--color-on-tertiary-fixed)",
  "background": "var(--color-background)",
  "on-primary-fixed": "var(--color-on-primary-fixed)",
  "on-surface": "var(--color-on-surface)",
  "surface": "var(--color-surface)",
  "inverse-on-surface": "var(--color-inverse-on-surface)",
  "on-primary-fixed-variant": "var(--color-on-primary-fixed-variant)",
  "on-primary-container": "var(--color-on-primary-container)",
  "nav-surface": "var(--color-nav-surface)",
  "topbar-surface": "var(--color-topbar-surface)"
};

module.exports = {
  content: ["./app/templates/**/*.html", "./app/static/js/**/*.js"],
  darkMode: "class",
  theme: {
    extend: {
      colors,
      fontFamily: {
        headline: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif"
        ],
        body: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif"
        ],
        label: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif"
        ]
      }
    }
  },
  plugins: [require("@tailwindcss/forms"), require("@tailwindcss/container-queries")]
};
