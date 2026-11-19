import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { api } from './api.js'
import Portfolio from './pages/Portfolio.jsx'
import DealerLookup from './pages/DealerLookup.jsx'
import OrderApproval from './pages/OrderApproval.jsx'
import ModelPage from './pages/ModelPage.jsx'

const PAGES = [
  ['/portfolio', 'Portfolio'],
  ['/lookup', 'Dealer lookup'],
  ['/order', 'Order approval'],
  ['/model', 'Model'],
]

// The logged-in supplier survives a page reload
const SUPPLIER_KEY = 'creditly.supplier'
function savedSupplier() {
  try { return localStorage.getItem(SUPPLIER_KEY) || 'A' } catch { return 'A' }
}

function Shell() {
  const navigate = useNavigate()
  const [suppliers, setSuppliers] = useState([])
  const [supplierId, setSupplierId] = useState(savedSupplier)
  const [dataVersion, setDataVersion] = useState(0)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.suppliers().then(setSuppliers).catch((e) => setError(e.message))
  }, [])

  const changeSupplier = (id) => {
    setSupplierId(id)
    try { localStorage.setItem(SUPPLIER_KEY, id) } catch { /* private mode: fine */ }
  }

  const props = { supplierId, dataVersion, openDealer: (gstin) => navigate(`/lookup/${gstin}`) }

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <span className="logo">C</span> Creditly
          <span className="tagline">network credit ratings for B2B dealers</span>
        </div>
        <nav className="nav">
          {PAGES.map(([path, label]) => (
            <NavLink key={path} to={path} className={({ isActive }) => (isActive ? 'active' : '')}>
              {label}
            </NavLink>
          ))}
        </nav>
        <label className="login">
          Logged in as
          <select value={supplierId} onChange={(e) => changeSupplier(e.target.value)}>
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </label>
      </header>

      <main className="main">
        {error && (
          <div className="error">
            Cannot reach the Creditly API ({error}). Is the backend running on port 8000?
          </div>
        )}
        <Routes>
          <Route path="/" element={<Navigate to="/portfolio" replace />} />
          <Route path="/portfolio" element={<Portfolio {...props} />} />
          <Route path="/lookup" element={<DealerLookup {...props} />} />
          <Route path="/lookup/:gstin" element={<DealerLookup {...props} />} />
          <Route path="/order" element={<OrderApproval {...props} />} />
          <Route path="/model" element={<ModelPage onRegenerated={() => setDataVersion((v) => v + 1)} />} />
          <Route path="*" element={<Navigate to="/portfolio" replace />} />
        </Routes>
      </main>
      <footer className="footer">All data is synthetic</footer>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  )
}
