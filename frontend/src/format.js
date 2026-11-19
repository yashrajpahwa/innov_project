// Indian number formatting: ₹18,40,000 and ₹4.2 cr / ₹47.7 L
export const inr = (x) => '₹' + Math.round(x || 0).toLocaleString('en-IN')

export function inrShort(x) {
  const v = x || 0
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(v >= 1e8 ? 0 : 2).replace(/\.?0+$/, '')} cr`
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(1).replace(/\.0$/, '')} L`
  return inr(v)
}

export const pct = (x, digits = 1) => `${(x * 100).toFixed(digits)}%`

export const RATINGS = ['AAA', 'AA', 'A', 'BBB', 'BB', 'B', 'C', 'D']

// Dark green (safest) to dark red (default)
export const RATING_COLORS = {
  AAA: '#0b5d1e', AA: '#2e7d32', A: '#5b9a2c', BBB: '#a8961a',
  BB: '#d97f06', B: '#cc4b1c', C: '#b0191e', D: '#6a0d12',
}
export const RATING_TEXT = { BBB: '#1c1c1c', BB: '#1c1c1c' }

export const TREND_ARROW = { down: '▼', up: '▲', flat: '–' }
