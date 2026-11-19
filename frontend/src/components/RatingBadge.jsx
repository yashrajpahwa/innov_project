import { RATING_COLORS, RATING_TEXT } from '../format.js'

export default function RatingBadge({ rating, size = 'sm' }) {
  return (
    <span
      className={`badge badge-${size}`}
      style={{ background: RATING_COLORS[rating], color: RATING_TEXT[rating] || '#fff' }}
      title={`Creditly rating ${rating}`}
    >
      {rating}
    </span>
  )
}

export function Trend({ trend, from }) {
  if (trend === 'flat') return <span className="trend flat" title="No change in 3 months">–</span>
  return (
    <span className={`trend ${trend}`} title={`Was ${from} three months ago`}>
      {trend === 'down' ? '▼' : '▲'} {from && <small>from {from}</small>}
    </span>
  )
}
