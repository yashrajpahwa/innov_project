import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { api } from '../api.js'
import { inr, inrShort, pct, RATINGS, RATING_COLORS } from '../format.js'
import RatingBadge, { Trend } from '../components/RatingBadge.jsx'

const axis = { fontSize: 12, fill: '#5f6b66' }

function RatingDot({ cx, cy, payload }) {
  return <circle cx={cx} cy={cy} r={6} fill={RATING_COLORS[payload.rating]} stroke="#fff" strokeWidth={2} />
}

function RatingHistory({ history }) {
  // Plot AAA at the top: y = 7 - index
  const data = history.map((h) => ({ ...h, y: 7 - RATINGS.indexOf(h.rating) }))
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={data} margin={{ top: 12, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="#eef1ef" />
        <XAxis dataKey="month" tick={axis} tickLine={false} axisLine={{ stroke: '#d5dbd8' }} />
        <YAxis domain={[0, 7]} ticks={[0, 1, 2, 3, 4, 5, 6, 7]} tickFormatter={(v) => RATINGS[7 - v]}
          tick={axis} tickLine={false} axisLine={false} width={40} />
        <Tooltip formatter={(v, n, p) => [`${p.payload.rating} (defaulting probability ${pct(p.payload.pd)})`, 'Rating']} />
        <Line type="linear" dataKey="y" stroke="#1d5c3a" strokeWidth={2} dot={<RatingDot />} activeDot={{ r: 8 }} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

function DbtChart({ trend }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={trend} margin={{ top: 12, right: 16, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} stroke="#eef1ef" />
        <XAxis dataKey="month" tick={axis} tickLine={false} axisLine={{ stroke: '#d5dbd8' }} interval={3} />
        <YAxis tick={axis} tickLine={false} axisLine={false} width={40} unit="d" />
        <Tooltip formatter={(v, name) => [v == null ? '–' : `${v} days`, name]} />
        <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
        <Line name="Whole network" dataKey="network" stroke="#c0392b" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
        <Line name="Your ledger" dataKey="yours" stroke="#1d5c3a" strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

export function DealerCard({ d }) {
  return (
    <div className="card rating-card">
      <div className="rating-head">
        <RatingBadge rating={d.rating} size="lg" />
        <div>
          <h2>{d.name}</h2>
          <div className="muted mono">{d.gstin} · {d.city}</div>
          <div className="small">
            Defaulting probability {pct(d.pd)} · <Trend trend={d.trend} from={d.rating_3m_ago} />
          </div>
        </div>
      </div>
      <div className="facts">
        <div><span>Network exposure</span><strong>{d.band}</strong></div>
        <div><span>Suggested limit (for you)</span><strong>{inrShort(d.suggested_limit)}</strong></div>
        <div><span>Owed to you</span><strong>{inr(d.own_outstanding)}</strong></div>
        <div><span>Your credit limit</span><strong>{inr(d.own_credit_limit)}</strong></div>
      </div>
    </div>
  )
}

export default function DealerLookup({ supplierId, dataVersion }) {
  const [dealers, setDealers] = useState([])
  const [query, setQuery] = useState('')
  // The dealer lives in the URL (/lookup/<GSTIN>), so a reload keeps it
  const navigate = useNavigate()
  const gstin = useParams().gstin || '07ABCDE1234F1Z5'
  const setGstin = (g) => navigate(`/lookup/${g}`)
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.dealers(supplierId).then(setDealers)
  }, [supplierId, dataVersion])

  useEffect(() => {
    if (!gstin) return
    setError(null)
    api.dealer(supplierId, gstin).then(setDetail).catch((e) => { setDetail(null); setError(e.message) })
  }, [supplierId, gstin, dataVersion])

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return []
    return dealers.filter((d) => d.name.toLowerCase().includes(q) || d.gstin.toLowerCase().includes(q)).slice(0, 8)
  }, [query, dealers])

  return (
    <>
      <h1>Dealer lookup</h1>
      <div className="search">
        <input
          placeholder="Search your dealers by name or GSTIN…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {matches.length > 0 && (
          <ul className="results">
            {matches.map((d) => (
              <li key={d.gstin} onClick={() => { setGstin(d.gstin); setQuery('') }}>
                <RatingBadge rating={d.rating} /> <span>{d.name}</span>
                <span className="muted mono small">{d.gstin}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {error && <div className="error">{error}. Try another dealer.</div>}
      {detail && (
        <>
          <DealerCard d={detail} />
          <div className="grid2">
            <div className="card">
              <h3>Rating history</h3>
              <RatingHistory history={detail.history} />
            </div>
            <div className="card">
              <h3>Why this rating <span className="muted small">top factors pushing risk up</span></h3>
              {detail.top_factors.length === 0 ? (
                <p className="muted">Nothing is pushing this dealer's risk above average.</p>
              ) : (
                <ol className="factors">
                  {detail.top_factors.map((f) => (
                    <li key={f.feature}>
                      <strong>{f.label}</strong>
                      <span className="muted">{f.value}</span>
                      <div className="factor-bar"><div style={{ width: `${Math.min(100, f.contribution * 60)}%` }} /></div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>
          <div className="card">
            <h3>Days beyond terms <span className="muted small">average lateness of invoices falling due each month</span></h3>
            <DbtChart trend={detail.dbt_trend} />
          </div>
        </>
      )}
    </>
  )
}
