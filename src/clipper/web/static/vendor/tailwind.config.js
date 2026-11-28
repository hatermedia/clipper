module.exports = {
  content: ["../index.html"],
  darkMode: "class",
  theme: {
    extend: {
      colors: { ink: '#06090f', panel: '#0b111b', panel2: '#0f1724' },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Consolas', 'monospace'],
      },
      boxShadow: {
        glow: '0 0 40px -12px rgba(34, 211, 238, 0.35)',
        card: '0 20px 60px -30px rgba(0, 0, 0, 0.8)',
      },
      keyframes: {
        rise: { '0%': { opacity: '0', transform: 'translateY(8px)' }, '100%': { opacity: '1', transform: 'translateY(0)' } },
        shimmer: { '0%': { backgroundPosition: '200% 0' }, '100%': { backgroundPosition: '-200% 0' } },
      },
      animation: { rise: 'rise .35s ease-out both', shimmer: 'shimmer 2s linear infinite' },
    },
  },
};
