/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#07080a", 900: "#0c0e11", 850: "#111317", 800: "#16191e", 700: "#1e2228", 600: "#2a2f37" },
        ember: { 300: "#ffb07a", 400: "#ff8a3d", 500: "#ff6a1a", 600: "#e5530a", 700: "#b33f06" },
        teal: { 300: "#7ef0e0", 400: "#34d6c4", 500: "#14b8a6" },
        alarm: { 400: "#ff5a52", 500: "#ef3b33", 600: "#c42620" },
      },
      fontFamily: { sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"], mono: ["JetBrains Mono", "Consolas", "monospace"] },
      boxShadow: {
        ember: "0 0 0 1px rgba(255,106,26,.45), 0 0 24px -4px rgba(255,106,26,.45)",
        panel: "0 1px 0 0 rgba(255,255,255,.04) inset, 0 20px 40px -20px rgba(0,0,0,.6)",
      },
      keyframes: {
        pulsering: { "0%": { transform: "scale(.6)", opacity: ".9" }, "100%": { transform: "scale(1.8)", opacity: "0" } },
        dash: { to: { strokeDashoffset: "-24" } },
        fadein: { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: { pulsering: "pulsering 2.4s ease-out infinite", dash: "dash 1.2s linear infinite", fadein: "fadein .25s ease-out" },
    },
  },
  plugins: [],
};
