const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed (${res.status})`)
  }
  return res.json()
}

export const api = {
  suppliers: () => request('/suppliers'),
  dealers: (sid) => request(`/dealers?supplier_id=${sid}`),
  dealer: (sid, gstin) => request(`/dealers/${gstin}?supplier_id=${sid}`),
  alerts: (sid) => request(`/alerts?supplier_id=${sid}`),
  checkOrder: (body) => request('/check-order', { method: 'POST', body: JSON.stringify(body) }),
  decideOrder: (body) => request('/orders', { method: 'POST', body: JSON.stringify(body) }),
  orders: (sid) => request(`/orders?supplier_id=${sid}`),
  resetOrders: () => request('/admin/reset-orders', { method: 'POST' }),
  metrics: () => request('/model/metrics'),
  regenerate: () => request('/admin/regenerate', { method: 'POST' }),
}
