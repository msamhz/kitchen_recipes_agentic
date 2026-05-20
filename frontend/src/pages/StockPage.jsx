import { useState, useEffect } from 'react'
import { Loader2, Trash2, RefreshCw, Pencil, Check, X, ChevronDown, ChevronUp } from 'lucide-react'
import { getStock, patchStock, deleteStock } from '../api'

const STORAGE_OPTIONS = ['fridge', 'freezer', 'pantry', 'counter']

function urgencyInfo(expiry, storage, inStock) {
  if (!inStock) return { border: '', labelColor: 'text-slate-400', label: '' }
  if (expiry) {
    const days = Math.ceil((new Date(expiry) - new Date()) / 86400000)
    if (days < 0)   return { border: 'border-l-4 border-l-red-400',    labelColor: 'text-red-500',    label: 'Expired' }
    if (days <= 2)  return { border: 'border-l-4 border-l-red-400',    labelColor: 'text-red-500',    label: `${days}d left` }
    if (days <= 7)  return { border: 'border-l-4 border-l-orange-400', labelColor: 'text-orange-500', label: `${days}d left` }
    if (days <= 30) return { border: 'border-l-4 border-l-yellow-400', labelColor: 'text-yellow-600', label: `${days}d left` }
    return            { border: 'border-l-4 border-l-green-400',  labelColor: 'text-green-600',  label: `${days}d left` }
  }
  if (storage === 'fridge' || storage === 'freezer')
    return { border: 'border-l-4 border-l-slate-300', labelColor: 'text-slate-400', label: 'No expiry' }
  return { border: '', labelColor: '', label: '' }
}

function urgencyScore(item) {
  if (!item.in_stock) return -1
  const { expiry_date: exp, storage_location: st } = item
  if (exp) {
    const d = Math.ceil((new Date(exp) - new Date()) / 86400000)
    if (d < 0)   return 1000
    if (d <= 3)  return 50
    if (d <= 7)  return 20
    if (d <= 30) return 5
    return 1
  }
  return (st === 'fridge' || st === 'freezer') ? 2 : 0
}

const byUrgency = (a, b) => urgencyScore(b) - urgencyScore(a)


function Section({ title, count, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-slate-700">{title}</span>
          <span className="text-xs bg-slate-100 text-slate-500 px-2 py-0.5 rounded-full">{count}</span>
        </div>
        {open ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
      </button>
      {open && <div className="border-t border-slate-100 p-3">{children}</div>}
    </div>
  )
}

function ItemCard({ item, reloadKey, onToggle, onStorage, onExpiryBlur, onDelete, onRename }) {
  const [expanded, setExpanded] = useState(false)
  const [editingName, setEditingName] = useState(false)
  const [nameInput, setNameInput] = useState(item.name)
  const info = urgencyInfo(item.expiry_date, item.storage_location, item.in_stock)

  // Compact date display: "27 Mar 27"
  const expiryDisplay = item.expiry_date
    ? (() => {
        const d = new Date(item.expiry_date + 'T00:00:00')
        return isNaN(d) ? item.expiry_date : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: '2-digit' })
      })()
    : null

  function handleSave() {
    const trimmed = nameInput.trim().toLowerCase()
    if (trimmed && trimmed !== item.name) onRename(item.id, trimmed)
    setEditingName(false)
  }

  return (
    <div className={`bg-white rounded-xl border border-slate-200 overflow-hidden ${info.border}`}>
      {/* Main row */}
      <div className="flex items-center gap-2 px-3 py-2.5">
        <div className="flex-1 min-w-0">
          {editingName ? (
            <div className="flex items-center gap-1">
              <input
                autoFocus
                value={nameInput}
                onChange={e => setNameInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') handleSave()
                  if (e.key === 'Escape') { setNameInput(item.name); setEditingName(false) }
                }}
                className="flex-1 text-sm font-medium text-slate-800 border-b border-orange-300 focus:outline-none bg-transparent capitalize min-w-0"
              />
              <button onClick={handleSave} className="text-green-500 p-0.5 shrink-0"><Check className="w-3.5 h-3.5" /></button>
              <button onClick={() => { setNameInput(item.name); setEditingName(false) }} className="text-slate-400 p-0.5 shrink-0"><X className="w-3.5 h-3.5" /></button>
            </div>
          ) : (
            <button
              onClick={() => { setNameInput(item.name); setEditingName(true) }}
              className="text-sm font-medium text-slate-800 capitalize leading-snug text-left block w-full truncate"
            >
              {item.name}
            </button>
          )}

          {/* Compact metadata row */}
          {!editingName && (
            <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
              {item.storage_location && (
                <span className="text-xs text-slate-400 capitalize">{item.storage_location}</span>
              )}
              {item.storage_location && (info.label || expiryDisplay) && (
                <span className="text-xs text-slate-300">·</span>
              )}
              {info.label ? (
                <span className={`text-xs ${info.labelColor}`}>{info.label}</span>
              ) : expiryDisplay ? (
                <span className="text-xs text-slate-400">{expiryDisplay}</span>
              ) : null}
              {item.expiry_source === 'label'    && <span className="text-xs px-1 rounded bg-green-100 text-green-700">label</span>}
              {item.expiry_source === 'estimate' && <span className="text-xs px-1 rounded bg-slate-100 text-slate-500">est.</span>}
              {item.expiry_source === 'manual'   && <span className="text-xs px-1 rounded bg-blue-100 text-blue-600">edited</span>}
            </div>
          )}
        </div>

        {/* Edit toggle (pencil) */}
        <button
          onClick={() => setExpanded(e => !e)}
          className={`shrink-0 p-1 rounded ${expanded ? 'text-orange-400' : 'text-slate-300 active:text-slate-500'}`}
        >
          <Pencil className="w-3.5 h-3.5" />
        </button>

        {/* In-stock toggle */}
        <button
          onClick={() => onToggle(item.id, !item.in_stock)}
          className={`w-9 h-5 rounded-full transition-colors shrink-0 relative ${item.in_stock ? 'bg-orange-400' : 'bg-slate-200'}`}
        >
          <div className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow-sm transition-all ${item.in_stock ? 'left-[17px]' : 'left-0.5'}`} />
        </button>

        {/* Delete */}
        <button onClick={() => onDelete(item.id)} className="text-slate-300 active:text-red-400 shrink-0 p-0.5">
          <Trash2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Expandable edit row */}
      {expanded && (
        <div className="flex items-center gap-2 px-3 pb-3 border-t border-slate-100 pt-2">
          <input
            key={`${item.id}-${reloadKey}`}
            type="date"
            defaultValue={item.expiry_date || ''}
            onBlur={e => onExpiryBlur(item.id, e.target.value, item.expiry_date)}
            className={`flex-1 text-xs border border-slate-200 rounded-lg px-2 py-1.5 bg-slate-50 focus:outline-none focus:border-orange-300 min-w-0 ${info.labelColor}`}
          />
          <select
            value={item.storage_location || ''}
            onChange={e => onStorage(item.id, e.target.value)}
            className="flex-1 text-xs border border-slate-200 rounded-lg px-2 py-1.5 bg-slate-50 focus:outline-none focus:border-orange-300 text-slate-700 min-w-0"
          >
            <option value="">—</option>
            {STORAGE_OPTIONS.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
          </select>
        </div>
      )}
    </div>
  )
}

export default function StockPage() {
  const [items, setItems]         = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [search, setSearch]       = useState('')


  async function load() {
    setLoading(true); setError(null)
    try {
      const data = await getStock()
      setItems([...data.ingredients].sort(byUrgency))
      setReloadKey(k => k + 1)
    } catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  async function handleToggle(id, value) {
    setItems(prev => [...prev].map(i => i.id === id ? { ...i, in_stock: value ? 1 : 0 } : i).sort(byUrgency))
    await patchStock(id, { in_stock: value ? 1 : 0 }).catch(load)
  }
  async function handleStorage(id, value) {
    setItems(prev => prev.map(i => i.id === id ? { ...i, storage_location: value || null } : i))
    await patchStock(id, { storage_location: value || null }).catch(load)
  }
  async function handleExpiryBlur(id, value, prev) {
    if (value === (prev || '')) return
    const source = value ? 'manual' : null
    setItems(items => items.map(i => i.id === id ? { ...i, expiry_date: value || null, expiry_source: source } : i))
    await patchStock(id, { expiry_date: value || null, expiry_source: source }).catch(load)
  }
  async function handleDelete(id) {
    setItems(prev => prev.filter(i => i.id !== id))
    await deleteStock(id).catch(load)
  }
  async function handleRename(id, newName) {
    setItems(prev => prev.map(i => i.id === id ? { ...i, name: newName } : i))
    await patchStock(id, { name: newName }).catch(load)
  }

  const filtered   = items.filter(i => i.name.toLowerCase().includes(search.toLowerCase()))
  const inStock    = filtered.filter(i => i.in_stock)
  const outOfStock = filtered.filter(i => !i.in_stock)

  const cardProps = {
    reloadKey,
    onToggle: handleToggle,
    onStorage: handleStorage,
    onExpiryBlur: handleExpiryBlur,
    onDelete: handleDelete,
    onRename: handleRename,
  }

  return (
    <>
      {/* Search + refresh */}
      <div className="flex items-center gap-2 px-4 py-2.5 bg-white border-b border-slate-100 sticky top-0 z-10">
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search ingredients…"
          className="flex-1 text-sm border border-slate-200 rounded-xl px-3 py-1.5 bg-slate-50 focus:outline-none focus:border-orange-300"
        />
        <button onClick={load} className="text-slate-400 p-1 active:text-slate-600 shrink-0">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {error && <div className="mx-4 mt-4 bg-red-50 text-red-700 text-sm px-4 py-3 rounded-xl border border-red-200">{error}</div>}

      {loading ? (
        <div className="flex-1 flex items-center justify-center min-h-48">
          <Loader2 className="w-8 h-8 text-orange-400 animate-spin" />
        </div>
      ) : (
        <div className="flex flex-col gap-3 p-4">

          {/* In Stock */}
          <Section title="In Stock" count={inStock.length} defaultOpen={true}>
            {inStock.length === 0
              ? <p className="text-xs text-slate-400 py-2 text-center">No items in stock</p>
              : <div className="flex flex-col gap-2">
                  {inStock.map(item => <ItemCard key={item.id} item={item} {...cardProps} />)}
                </div>
            }
          </Section>

          {/* Out of Stock */}
          <Section title="Out of Stock" count={outOfStock.length} defaultOpen={true}>
            {outOfStock.length === 0
              ? <p className="text-xs text-slate-400 py-2 text-center">Nothing out of stock</p>
              : <div className="flex flex-col gap-2">
                  {outOfStock.map(item => <ItemCard key={item.id} item={item} {...cardProps} />)}
                </div>
            }
          </Section>

        </div>
      )}
    </>
  )
}
