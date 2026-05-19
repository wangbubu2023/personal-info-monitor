/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: 'var(--color-primary)',
          hover: 'var(--color-primary-hover)',
          light: 'var(--color-primary-light)',
        },
        slate: {
          950: '#020617',
        },
        background: 'var(--color-background)',
        surface: 'var(--color-surface)',
        text: {
          DEFAULT: 'var(--color-text)',
          secondary: 'var(--color-text-secondary)',
          muted: 'var(--color-text-muted)',
        },
      },
      backgroundImage: {
        'glass-gradient': 'linear-gradient(to bottom right, rgba(255, 255, 255, 0.05), rgba(255, 255, 255, 0))',
      },
      backdropBlur: {
        'xs': '2px',
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
      maxWidth: {
        page: 'var(--max-width-page)',
        feed: 'var(--max-width-feed)',
      },
      borderRadius: {
        'xl': 'var(--radius-xl)',
        '2xl': '1.5rem',
      },
      boxShadow: {
        'premium': 'var(--shadow-lg)',
        'glow': 'var(--shadow-glow)',
      },
    },
  },
  plugins: [],
  // 不要让 Tailwind 的 preflight 与 Ant Design 冲突
  corePlugins: {
    preflight: false,
  },
}
