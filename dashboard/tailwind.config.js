/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f2f6ff",
          100: "#e6edff",
          400: "#5b7fff",
          500: "#3f63f2",
          600: "#2f4fd9",
          700: "#263fae",
        },
      },
    },
  },
  plugins: [],
};
