import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { inr, inrShort, pct } from '../format.js'
import RatingBadge from '../components/RatingBadge.jsx'

const STORY_GSTIN = '07ABCDE1234F1Z5'
const REC_CLASS = { Approve: 'ok', 'Approve with reduced limit': 'warn', Hold: 'bad' }

export default function OrderApproval({ supplierId, dataVersion }) {
  const [dealers, setDealers] = useState([])
  // Dealer and order value live in the URL (?gstin=…&value=…), so a reload keeps them
  const [params, setParams] = useSearchParams()
  const gstin = params.get('gstin') || STORY_GSTIN
  const orderValue = params.get('value') ?? '1840000'
  const setGstin = (g) => setParams({ gstin: g, value: orderValue }, { replace: true })
  const setOrderValue = (v) => setParams({ gstin, value: v }, { replace: true })
  const [check, setCheck] = useState(null)
  const [result, setResult] = useState(null)
  const [orders, setOrders] = useState([])
  const [busy, setBusy] = useState(false)
  const [refreshKey, setRefreshKey] = useState(0)

  useEffect(() => {
    api.dealers(supplierId).then((rows) => {
      const sorted = [...rows].sort((a, b) => a.name.localeCompare(b.name))
      setDealers(sorted)
      if (!rows.some((d) => d.gstin === gstin)) setGstin(rows.some((d) => d.gstin === STORY_GSTIN) ? STORY_GSTIN : sorted[0]?.gstin)
    })
    api.orders(supplierId).then(setOrders)
  }, [supplierId, dataVersion, refreshKey])

  // A new dealer or amount is a new order: clear the last decision message
  useEffect(() => setResult(null), [supplierId, gstin, orderValue])

  const decide = async (decision) => {
    setBusy(true)
    try {
      const r = await api.decideOrder({ supplier_id: supplierId, gstin, order_value: Number(orderValue) || 0, decision })
      setResult(r)
      setRefreshKey((k) => k + 1)   // reload owed-to-us, rating and the decisions log
    } catch (e) {
      setResult({ decision: 'error', message: e.message })
    } finally {
      setBusy(false)
    }
  }

  const reset = async () => {
    await api.resetOrders()
    setResult(null)
    setRefreshKey((k) => k + 1)
  }

  useEffect(() => {
    if (!gstin || !dealers.some((d) => d.gstin === gstin)) return
    const t = setTimeout(() => {
      api.checkOrder({ supplier_id: supplierId, gstin, order_value: Number(orderValue) || 0 })
        .then(setCheck).catch(() => setCheck(null))
    }, 250)
    return () => clearTimeout(t)
  }, [supplierId, gstin, orderValue, dealers])

  const dealer = dealers.find((d) => d.gstin === gstin)
  const owed = dealer?.own_outstanding || 0
  const limit = dealer?.own_credit_limit || 0
  const available = limit - owed
  const withinOurLimit = owed + Number(orderValue) <= limit

  return (
    <>
      <h1>Order approval</h1>
      <p className="muted">Your ERP's sales-order screen, with the Creditly panel alongside it.</p>
      <div className="order-layout">
        {/* ---------- Mock ERP ---------- */}
        <div className="erp">
          <div className="erp-title">
            <span>Sales Order</span><span className="mono">SO/2026-27/{String(1123 + orders.length).padStart(5, '0')}</span>
          </div>
          <div className="erp-body">
            <label>Customer
              <select value={gstin || ''} onChange={(e) => setGstin(e.target.value)}>
                {dealers.map((d) => <option key={d.gstin} value={d.gstin}>{d.name}</option>)}
              </select>
            </label>
            <div className="erp-row">
              <label>GSTIN<input value={gstin || ''} readOnly className="mono" /></label>
              <label>Order date<input value="20-11-2026" readOnly /></label>
            </div>
            <table className="erp-lines">
              <thead><tr><th>Item</th><th className="num">Qty</th><th className="num">Rate</th><th className="num">Amount</th></tr></thead>
              <tbody>
                <tr><td>Business laptop 14" i5 / 16 GB / 512 GB</td><td className="num">28</td><td className="num">₹52,500</td><td className="num">₹14,70,000</td></tr>
                <tr><td>Laptop docking station</td><td className="num">40</td><td className="num">₹9,250</td><td className="num">₹3,70,000</td></tr>
              </tbody>
            </table>
            <label>Order value (₹)
              <input type="number" value={orderValue} onChange={(e) => setOrderValue(e.target.value)} />
              <span className="muted small">{inr(orderValue)}</span>
            </label>
            <div className="erp-credit">
              <div><span>Owed to us</span><strong>{inr(owed)}</strong></div>
              <div><span>Our credit limit</span><strong>{inr(limit)}</strong></div>
              <div><span>Available</span><strong>{inr(available)}</strong></div>
            </div>
            <div className={`erp-status ${withinOurLimit ? 'ok' : 'bad'}`}>
              {withinOurLimit ? '✔ Within our credit limit' : '✖ Exceeds our credit limit'}
            </div>
          </div>
        </div>

        {/* ---------- Creditly panel ---------- */}
        <div className="creditly-panel">
          <div className="panel-title"><span className="logo">C</span> Creditly check</div>
          {!check ? <p className="muted">Checking…</p> : (
            <>
              <div className="panel-rating">
                <RatingBadge rating={check.rating} size="lg" />
                <div>
                  <div className="small muted">Network rating</div>
                  <div>
                    Defaulting probability {pct(check.pd)}
                    {check.trend === 'down' && <span className="trend down"> ▼ from {check.rating_3m_ago}</span>}
                  </div>
                </div>
              </div>
              <div className="facts single">
                <div><span>Network exposure</span><strong>{check.band}</strong></div>
                <div><span>Suggested limit for you</span><strong>{inrShort(check.suggested_limit)}</strong></div>
                <div><span>Your exposure after order</span><strong>{inrShort(check.exposure_after_order)}</strong></div>
              </div>
              <div className="impact">
                <span className="small muted">Model re-rating if you approve</span>
                <div>
                  <RatingBadge rating={check.rating} /> → <RatingBadge rating={check.if_approved.rating} />
                  <span className="small"> Defaulting probability {pct(check.pd)} → {pct(check.if_approved.pd)}</span>
                </div>
              </div>
              <div className={`recommendation ${REC_CLASS[check.recommendation]}`}>
                <strong>{check.recommendation}</strong>
                {check.recommendation === 'Approve with reduced limit' && <span> up to {inr(check.approved_amount)}</span>}
                <p>{check.reason}</p>
              </div>
              <div className="actions">
                <button className="btn approve" disabled={busy} onClick={() => decide('approve')}>Approve</button>
                <button className="btn hold" disabled={busy} onClick={() => decide('hold')}>Hold</button>
              </div>
              {busy && <p className="decision">Re-running the model…</p>}
              {result && !busy && (
                <p className={`decision ${result.decision}`}>
                  {result.message}
                  {result.after && result.after.rating !== result.before.rating && (
                    <>{' '}Rating <RatingBadge rating={result.before.rating} /> → <RatingBadge rating={result.after.rating} /></>
                  )}
                </p>
              )}
              <p className="muted small">Creditly shows only the rating and exposure band. Other suppliers' names and amounts are never shared.</p>
            </>
          )}
        </div>
      </div>

      <div className="card">
        <h3>
          Your order decisions
          <span className="muted small"> approved orders are booked into your ledger and the model re-rates the dealer for every supplier</span>
        </h3>
        {orders.length === 0 ? (
          <p className="muted">No decisions yet. Approve or hold an order above.</p>
        ) : (
          <>
            <table className="table">
              <thead>
                <tr><th>Order</th><th>Dealer</th><th className="num">Value</th><th>Decision</th><th>Rating</th><th className="num">Defaulting probability</th></tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.order_id}>
                    <td className="mono">{o.order_id}<div className="muted small">{o.created_at.replace('T', ' ')}</div></td>
                    <td>{o.name}</td>
                    <td className="num">{inr(o.order_value)}</td>
                    <td><span className={`tag ${o.decision}`}>{o.decision === 'approve' ? 'Approved' : 'Held'}</span></td>
                    <td><RatingBadge rating={o.rating_before} /> → <RatingBadge rating={o.rating_after} /></td>
                    <td className="num">{pct(o.pd_before)} → {pct(o.pd_after)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <button className="btn secondary" onClick={reset}>Reset all decisions</button>
          </>
        )}
      </div>
    </>
  )
}
