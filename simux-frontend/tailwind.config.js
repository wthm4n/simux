/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: ["'JetBrains Mono'", "'Fira Code'", "monospace"],
        sans: ["'DM Sans'", "sans-serif"],
      },
      colors: {
        bg:      "#0a0a0a",
        surface: "#111111",
        card:    "#161616",
        border:  "#222222",
        muted:   "#333333",
        red: {
          400: "#f87171",
          500: "#ef4444",
          600: "#dc2626",
          700: "#b91c1c",
          900: "#450a0a",
        },
      },
      animation: {
        "pulse-slow": "pulse 2s cubic-bezier(0.4,0,0.6,1) infinite",
        "fade-in":    "fadeIn 0.3s ease forwards",
        "slide-up":   "slideUp 0.4s ease forwards",
      },
      keyframes: {
        fadeIn:  { from: { opacity: 0 }, to: { opacity: 1 } },
        slideUp: { from: { opacity: 0, transform: "translateY(12px)" }, to: { opacity: 1, transform: "translateY(0)" } },
      },
    },
  },
  plugins: [],
}