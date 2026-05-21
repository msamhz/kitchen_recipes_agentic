import { useState, useRef } from 'react'
import { Camera, CheckCircle2, Circle, Loader2, RefreshCw, Plus, Pencil } from 'lucide-react'
import { scanImages, upsertStock, normaliseName } from '../api'
import { compressImage } from '../utils/compressImage'

const STORAGE_OPTIONS = ['fridge', 'freezer', 'pantry', 'counter']

const CONFIDENCE_COLOR = {
  high:   'bg-green-100 text-green-700',
  medium: 'bg-yellow-100 text-yellow-700',
  low:    'bg-slate-100 text-slate-500',
  manual: 'bg-blue-100 text-blue-600',
}

function expiryColor(date) {
  if (!date) return 'text-slate-400'
  const days = Math.ceil((new Date(date) - new Date()) / 86400000)
  if (days <= 2)  return 'text-red-600 font-semibold'
  if (days <= 7)  return 'text-orange-500'
  if (days <= 30) return 'text-yellow-600'
  return 'text-green-600'
}

function CandidateCard({ c, selected, onToggle, edits, setField, getField }) {
  const [editingName, setEditingName] = useState(!!c.isManual)
  const [hint, setHint] = useState(null) // canonical name suggestion from vector index

  const on = selected.has(c.name)
  const displayName = edits[c.name]?.name ?? c.name
  const expiry  = getField(c.name, 'expiry_date')
  const storage = getField(c.name, 'storage_location')

  async function handleNameBlur() {
    const typed = (edits[c.name]?.name ?? '').trim().toLowerCase()
    if (!typed) { setEditingName(false); return }
    setEditingName(false)
    try {
      const result = await normaliseName(typed)
      if (result.changed) {
        setField(c.name, 'name', result.canonical)
        setHint(result.canonical)
        setTimeout(() => setHint(null), 3000)
      }
    } catch {}
  }

  return (
    <div className={`bg-white rounded-xl border transition-colors ${on ? 'border-orange-300' : 'border-slate-200'}`}>
      {/* Header row */}
      <div className="flex items-start gap-3 p-4">
        <div className="mt-0.5 shrink-0 cursor-pointer" onClick={() => onToggle(c.name)}>
          {on
            ? <CheckCircle2 className="w-5 h-5 text-orange-500" />
            : <Circle       className="w-5 h-5 text-slate-300" />}
        </div>

        <div className="flex-1 min-w-0">
          {editingName ? (
            <input
              autoFocus
              value={edits[c.name]?.name ?? ''}
              onChange={e => setField(c.name, 'name', e.target.value)}
              onBlur={handleNameBlur}
              onKeyDown={e => {
                if (e.key === 'Enter')  handleNameBlur()
                if (e.key === 'Escape') { setField(c.name, 'name', c.isManual ? '' : c.name); setEditingName(false) }
              }}
              placeholder="Ingredient name…"
              className="w-full text-sm font-medium text-slate-800 border-b border-orange-300 focus:outline-none bg-transparent capitalize min-w-0"
            />
          ) : (
            <button
              onClick={() => { setField(c.name, 'name', displayName); setEditingName(true) }}
              className="flex items-center gap-1.5 text-sm font-medium text-slate-800 capitalize leading-snug text-left w-full truncate"
            >
              {displayName && !displayName.startsWith('__manual')
                ? displayName
                : <span className="text-slate-400 italic font-normal">tap to name…</span>}
              <Pencil className="w-3 h-3 text-slate-300 shrink-0" />
            </button>
          )}

          {/* Normalise hint — shows when vector index found a cleaner canonical */}
          {hint && (
            <p className="text-xs text-blue-500 mt-0.5 animate-pulse">simplified → {hint}</p>
          )}

          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            <span className={`text-xs px-2 py-0.5 rounded-full ${CONFIDENCE_COLOR[c.confidence] ?? CONFIDENCE_COLOR.low}`}>
              {c.confidence}
            </span>
            {c.expiry_source === 'label'    && <span className="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700">label</span>}
            {c.expiry_source === 'estimate' && <span className="text-xs px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">est.</span>}
            {c.notes && <span className="text-xs text-slate-400 truncate">{c.notes}</span>}
          </div>
        </div>
      </div>

      {/* Expiry + storage */}
      <div className="px-4 pb-3 flex flex-col gap-1.5 border-t border-slate-100 pt-2.5">
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400 w-14 shrink-0">Expiry</label>
          <input
            type="date"
            value={expiry || ''}
            onChange={e => setField(c.name, 'expiry_date', e.target.value)}
            className={`flex-1 text-xs border border-slate-200 rounded-lg px-2 py-1.5 bg-slate-50 focus:outline-none focus:border-orange-300 ${expiryColor(expiry)}`}
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400 w-14 shrink-0">Storage</label>
          <select
            value={storage || ''}
            onChange={e => setField(c.name, 'storage_location', e.target.value)}
            className="flex-1 text-xs border border-slate-200 rounded-lg px-2 py-1.5 bg-slate-50 focus:outline-none focus:border-orange-300 text-slate-700"
          >
            <option value="">Unknown</option>
            {STORAGE_OPTIONS.map(s => <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
          </select>
        </div>
      </div>
    </div>
  )
}

export default function ScanPage() {
  const [phase, setPhase]           = useState('idle')
  const [candidates, setCandidates] = useState([])
  const [selected, setSelected]     = useState(new Set())
  const [edits, setEdits]           = useState({})
  const [error, setError]           = useState(null)
  const inputRef = useRef()

  function getField(name, field) {
    return edits[name]?.[field] ?? candidates.find(c => c.name === name)?.[field] ?? ''
  }

  function setField(name, field, value) {
    setEdits(prev => ({ ...prev, [name]: { ...prev[name], [field]: value } }))
  }

  function getExpirySource(name) {
    const original  = candidates.find(c => c.name === name)
    const editedDate = edits[name]?.expiry_date
    if (editedDate !== undefined && editedDate !== (original?.expiry_date ?? '')) return 'manual'
    return original?.expiry_source || null
  }

  function addManual() {
    const key  = `__manual_${Date.now()}`
    const item = { name: key, confidence: 'manual', expiry_date: null, expiry_source: null, storage_location: null, notes: '', isManual: true }
    setCandidates(prev => [...prev, item])
    setSelected(prev => new Set([...prev, key]))
    setEdits(prev => ({ ...prev, [key]: { name: '' } }))
    if (phase === 'idle') setPhase('results')
  }

  async function handleFiles(files) {
    if (!files.length) return
    setPhase('scanning'); setError(null)
    try {
      const compressed = await Promise.all(files.map(compressImage))
      const data = await scanImages(compressed)
      setCandidates(data.candidates)
      setSelected(new Set(data.candidates.map(c => c.name)))
      setEdits({})
      setPhase('results')
    } catch (e) {
      setError(e.message); setPhase('idle')
    }
  }

  function toggle(name) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })
  }

  async function confirm() {
    setPhase('confirming')
    const chosen = candidates.filter(c => selected.has(c.name))

    // Resolve each candidate to its final name (edited > original; skip manual with no name)
    const items = chosen
      .map(c => {
        const edited    = (edits[c.name]?.name ?? '').trim().toLowerCase()
        const finalName = edited || (c.isManual ? null : c.name)
        return { c, finalName }
      })
      .filter(({ finalName }) => !!finalName)

    const names    = items.map(({ finalName }) => finalName)
    const metadata = Object.fromEntries(
      items.map(({ c, finalName }) => [finalName, {
        expiry_date:      getField(c.name, 'expiry_date') || null,
        expiry_source:    c.isManual ? (getField(c.name, 'expiry_date') ? 'manual' : null) : getExpirySource(c.name),
        storage_location: getField(c.name, 'storage_location') || null,
      }])
    )

    try {
      await upsertStock(names, 'restock', metadata)
      setPhase('done')
    } catch (e) {
      setError(e.message); setPhase('results')
    }
  }

  function reset() {
    setPhase('idle'); setCandidates([]); setSelected(new Set()); setEdits({}); setError(null)
  }

  // Count items that will actually be saved (manual items need a name)
  const countToAdd = candidates.filter(c => {
    if (!selected.has(c.name)) return false
    return c.isManual ? (edits[c.name]?.name ?? '').trim().length > 0 : true
  }).length

  return (
    <main className="flex-1 p-4 flex flex-col gap-3">

      {/* IDLE */}
      {phase === 'idle' && (
        <>
          <input ref={inputRef} type="file" accept="image/*" multiple className="hidden"
            onChange={e => handleFiles([...e.target.files])} />
          {error && (
            <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-xl border border-red-200">{error}</div>
          )}
          <button
            onClick={() => inputRef.current.click()}
            className="flex-1 flex flex-col items-center justify-center gap-4 bg-white rounded-2xl border-2 border-dashed border-slate-200 min-h-64 active:bg-slate-50 transition-colors"
          >
            <div className="w-16 h-16 rounded-full bg-orange-50 flex items-center justify-center">
              <Camera className="w-8 h-8 text-orange-500" />
            </div>
            <div className="text-center">
              <p className="font-medium text-slate-700">Scan your kitchen</p>
              <p className="text-sm text-slate-400 mt-1">Tap to take a photo or upload</p>
            </div>
          </button>

          <button
            onClick={addManual}
            className="flex items-center justify-center gap-2 py-3 bg-white rounded-xl border border-slate-200 text-sm text-slate-600 active:bg-slate-50"
          >
            <Plus className="w-4 h-4 text-orange-500" />
            Add item manually
          </button>
        </>
      )}

      {/* SCANNING / CONFIRMING */}
      {(phase === 'scanning' || phase === 'confirming') && (
        <div className="flex-1 flex flex-col items-center justify-center gap-3 min-h-72">
          <Loader2 className="w-10 h-10 text-orange-500 animate-spin" />
          <p className="text-slate-500 text-sm">
            {phase === 'scanning' ? 'Identifying ingredients…' : 'Saving to pantry…'}
          </p>
        </div>
      )}

      {/* RESULTS */}
      {phase === 'results' && (
        <>
          <div className="flex items-center justify-between">
            <p className="text-sm text-slate-500">{candidates.length} found · select to add</p>
            <div className="flex items-center gap-2">
              <button onClick={addManual} className="text-orange-500 p-1 active:text-orange-600" title="Add manually">
                <Plus className="w-4 h-4" />
              </button>
              <button onClick={reset} className="text-sm text-slate-400 flex items-center gap-1 active:text-slate-600">
                <RefreshCw className="w-3 h-3" /> Rescan
              </button>
            </div>
          </div>
          {error && (
            <div className="bg-red-50 text-red-700 text-sm px-4 py-3 rounded-xl border border-red-200">{error}</div>
          )}
          <div className="flex flex-col gap-2">
            {candidates.map(c => (
              <CandidateCard
                key={c.name}
                c={c}
                selected={selected}
                onToggle={toggle}
                edits={edits}
                setField={setField}
                getField={getField}
              />
            ))}
          </div>
        </>
      )}

      {/* DONE */}
      {phase === 'done' && (
        <div className="flex-1 flex flex-col items-center justify-center gap-4 min-h-72">
          <div className="w-16 h-16 rounded-full bg-green-50 flex items-center justify-center">
            <CheckCircle2 className="w-8 h-8 text-green-500" />
          </div>
          <div className="text-center">
            <p className="font-semibold text-slate-800">Added to pantry!</p>
            <p className="text-sm text-slate-400 mt-1">{countToAdd} ingredient{countToAdd !== 1 ? 's' : ''} saved</p>
          </div>
          <button onClick={reset} className="mt-2 px-6 py-2.5 bg-orange-500 text-white rounded-xl font-medium text-sm active:bg-orange-600">
            Scan again
          </button>
        </div>
      )}

      {/* Sticky confirm */}
      {phase === 'results' && countToAdd > 0 && (
        <div className="sticky bottom-0 -mx-4 px-4 pb-4 pt-2 bg-gradient-to-t from-slate-50">
          <button onClick={confirm} className="w-full py-3 bg-orange-500 text-white rounded-xl font-medium active:bg-orange-600">
            Add {countToAdd} item{countToAdd !== 1 ? 's' : ''} to pantry
          </button>
        </div>
      )}
    </main>
  )
}
