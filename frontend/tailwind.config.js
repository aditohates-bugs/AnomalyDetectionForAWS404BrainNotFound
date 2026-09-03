/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        obsidian: {
          950: '#080C14',
          900: '#0E1524',
          800: '#162032',
          700: '#202D42',
        },
        telemetry: {
          teal: '#0D9488',
          cyan: '#0EA5E9',
          amber: '#F59E0B',
          yellow: '#EAB308',
          crimson: '#EF4444',
          dim: '#475569',
        }
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Space Mono"', 'monospace'],
        sans: ['"Inter"', 'sans-serif'],
      }
    },
  },
  plugins: [],
}
