/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Soft blue-violet accent. Used for the main action on a page and for
        // "you are here"; everything else stays calm.
        brand: {
          50: "#f3f2ff",
          100: "#e8e6ff",
          200: "#d3d0ff",
          400: "#7f7bff",
          500: "#5b57f5",
          600: "#4a45e0",
          700: "#3b36b8",
        },
        ink: {
          900: "#1c1b3a",
          700: "#3a3957",
          500: "#6b6a88",
          400: "#8f8ea8",
          300: "#b9b8cc",
        },
        canvas: "#f4f2fb",
      },
      fontFamily: {
        sans: [
          "Plus Jakarta Sans",
          "ui-rounded",
          "SF Pro Rounded",
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      borderRadius: {
        "2xl": "1.25rem",
        "3xl": "1.75rem",
      },
      boxShadow: {
        soft: "0 1px 2px rgba(31, 27, 46, 0.05), 0 10px 28px rgba(75, 50, 184, 0.07)",
        lift: "0 2px 4px rgba(31, 27, 46, 0.06), 0 16px 36px -8px rgba(75, 50, 184, 0.22)",
        glow: "0 6px 18px -4px rgba(91, 87, 245, 0.45)",
      },
      keyframes: {
        pop: {
          "0%": { transform: "scale(0.4)", opacity: "0" },
          "60%": { transform: "scale(1.15)", opacity: "1" },
          "100%": { transform: "scale(1)" },
        },
        rise: {
          "0%": { transform: "translateY(6px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
      },
      animation: {
        pop: "pop 380ms ease-out both",
        rise: "rise 260ms ease-out both",
      },
    },
  },
  plugins: [],
};
