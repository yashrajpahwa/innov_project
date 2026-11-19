import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../api.js'
import { inrShort, RATINGS, RATING_COLORS } from '../format.js'
import RatingBadge, { Trend } from '../components/RatingBadge.jsx'

const axis = { fontSize: 12, fill: '#5f6b66' }

function RatingBars({ data, dataKey, formatter, title }) {
  return (
    <div className="card">
      <h3>{title}</h3>
      <ResponsiveContainer width="100%" height={240}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="18%">
          <CartesianGrid vertical={false} stroke="#eef1ef" />
          <XAxis dataKey="rating" tick={axis} tickLine={false} axisLine={{ stroke: '#d5dbd8' }} />
          <YAxis tick={axis} tickLine={false} axisLine={false} tickFormatter={formatter} width={64} />
          <Tooltip cursor={{ fill: '#f3f6f4' }} formatter={(v) => [formatter(v), title]} />
          <Bar dataKey={dataKey} radius={[4, 4, 0, 0]}>
            {data.map((d) => (
              <Cell key={d.rating} fill={RATING_COLORS[d.rating]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

export default function Portfolio({ supplierId, dataVersion, openDealer }) {
  const [dealers, setDealers] = useState(null)
  const [alerts, setAlerts] = useState([])

  useEffect(() => {
    setDealers(null)
    api.dealers(supplierId).then(setDealers)
    api.alerts(supplierId).then(setAlerts)
  }, [supplierId, dataVersion])

  if (!dealers) return <p className="muted">Loading portfolio…</p>

  const byRating = RATINGS.map((r) => {
    const rows = dealers.filter((d) => d.rating === r)
    return { rating: r, count: rows.length, exposure: rows.reduce((s, d) => s + d.own_outstanding, 0) }
  })
  const totalOwed = dealers.reduce((s, d) => s + d.own_outstanding, 0)
  const risky = dealers.filter((d) => ['C', 'D'].includes(d.rating))
  const riskyOwed = risky.reduce((s, d) => s + d.own_outstanding, 0)

  return (
    <>
      <h1>Portfolio</h1>
      <p className="muted">Your dealers, rated on their behaviour across the whole Creditly network.</p>

      <div className="tiles">
        <div className="tile"><span>Dealers</span><strong>{dealers.length}</strong></div>
        <div className="tile"><span>Owed to you</span><strong>{inrShort(totalOwed)}</strong></div>
        <div className="tile"><span>Downgraded in 3 months</span><strong>{alerts.length}</strong></div>
        <div className="tile"><span>Owed by C / D dealers</span><strong>{inrShort(riskyOwed)}</strong></div>
      </div>

      <div className="grid2">
        <RatingBars data={byRating} dataKey="count" title="Dealers by rating" formatter={(v) => v} />
        <RatingBars data={byRating} dataKey="exposure" title="Owed to you by rating" formatter={inrShort} />
      </div>

      <div className="card">
        <h3>Downgrade alerts <span className="muted small">rating fell in the last 3 months</span></h3>
        {alerts.length === 0 ? (
          <p className="muted">No downgrades. 🎉</p>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Dealer</th><th>GSTIN</th><th>Rating</th><th>Change</th><th>Network exposure</th><th className="num">Owed to you</th><th className="num">Suggested limit</th></tr>
            </thead>
            <tbody>
              {alerts.map((a) => (
                <tr key={a.gstin} className="clickable" onClick={() => openDealer(a.gstin)}>
                  <td>{a.name}<div className="muted small">{a.city}</div></td>
                  <td className="mono">{a.gstin}</td>
                  <td><RatingBadge rating={a.rating} /></td>
                  <td><Trend trend={a.trend} from={a.rating_3m_ago} /></td>
                  <td>{a.band}</td>
                  <td className="num">{inrShort(a.own_outstanding)}</td>
                  <td className="num">{inrShort(a.suggested_limit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
