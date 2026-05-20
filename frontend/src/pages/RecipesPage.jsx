import { useState, useEffect } from 'react'
import { Loader2, Trash2, RefreshCw, Plus, X, ChevronDown, ChevronUp, CheckSquare, Link, AlertTriangle } from 'lucide-react'
import { getRecipes, createRecipe, deleteRecipe, markUsed, parseRecipeUrl } from '../api'

// ─── Helpers ────────────────────────────────────────────────────────────────

function diffColor(d) {
  const v = (d || '').toLowerCase()
  if (v === 'easy')   return 'bg-green-100 text-green-700'
  if (v === 'medium') return 'bg-amber-100 text-amber-700'
  if (v === 'hard')   return 'bg-red-100 text-red-700'
  return 'bg-slate-100 text-slate-600'
}

function fmtTime(t) {
  if (!t) return null
  if (t === 'under_10') return '<10 mins'
  if (t === '10_to_20') return '10-20 mins'
  if (t === 'over_20')  return '20+ mins'
  return t.replace(/(\d+)\s*min\b/, '$1 mins')
}

function urgencyBorder(score) {
  if (score >= 50) return 'border-l-4 border-l-red-400'
  if (score >= 20) return 'border-l-4 border-l-orange-400'
  if (score >= 5)  return 'border-l-4 border-l-yellow-400'
  if (score >= 2)  return 'border-l-4 border-l-slate-300'
  return ''
}

function urgencyChip(score) {
  if (score >= 50) return { text: 'Use now!',      cls: 'bg-red-100 text-red-600 font-semibold' }
  if (score >= 20) return { text: 'Use soon',      cls: 'bg-orange-100 text-orange-600' }
  if (score >= 5)  return { text: 'Use this week', cls: 'bg-yellow-100 text-yellow-700' }
  return null
}

function expiryChipCls(days) {
  if (days < 0)   return 'bg-red-100 text-red-600'
  if (days <= 2)  return 'bg-red-100 text-red-600'
  if (days <= 7)  return 'bg-orange-100 text-orange-600'
  return 'bg-yellow-100 text-yellow-700'
}

// ─── Expiry notification bar ─────────────────────────────────────────────────

function ExpiryBar({ recipes }) {
  const seen = {}
  for (const r of recipes) {
    for (const e of (r.expiring_ingredients || [])) {
      if (!seen[e.name] || seen[e.name].days_left > e.days_left) seen[e.name] = e
    }
  }
  const items = Object.values(seen).sort((a, b) => a.days_left - b.days_left).slice(0, 6)
  if (items.length === 0) return null

  return (
    <div className="mx-4 mt-3 bg-orange-50 border border-orange-200 rounded-xl px-3 py-2.5">
      <div className="flex items-center gap-1.5 mb-1.5">
        <AlertTriangle className="w-3.5 h-3.5 text-orange-500" />
        <p className="text-xs font-medium text-orange-700">Use before they expire</p>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map(e => (
          <span key={e.name} className={`text-xs px-2 py-0.5 rounded-full capitalize ${expiryChipCls(e.days_left)}`}>
            {e.name} {e.days_left < 0 ? '(expired)' : e.days_left === 0 ? '(today)' : `(${e.days_left}d)`}
          </span>
        ))}
      </div>
    </div>
  )
}

// ─── Mark Cooked modal ───────────────────────────────────────────────────────

function MarkCookedModal({ recipe, onConfirm, onCancel, saving }) {
  const [checked, setChecked] = useState(new Set(recipe.have))

  function toggle(name) {
    setChecked(prev => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-end justify-center p-0" onClick={onCancel}>
      <div
        className="bg-white rounded-t-2xl w-full max-w-md px-5 pt-5 pb-8"
        onClick={e => e.stopPropagation()}
      >
        <p className="font-semibold text-slate-800 text-base">{recipe.name}</p>
        <p className="text-xs text-slate-500 mt-0.5 mb-4">Select ingredients used — they'll be marked out of stock</p>

        <div className="flex flex-col gap-1 max-h-56 overflow-y-auto mb-5">
          {recipe.have.map(name => (
            <label key={name} className="flex items-center gap-3 py-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={checked.has(name)}
                onChange={() => toggle(name)}
                className="w-4 h-4 accent-orange-500 rounded"
              />
              <span className="text-sm text-slate-700 capitalize">{name}</span>
            </label>
          ))}
        </div>

        <div className="flex gap-2">
          <button onClick={onCancel} className="flex-1 py-2.5 border border-slate-200 rounded-xl text-sm text-slate-600 active:bg-slate-50">
            Cancel
          </button>
          <button
            onClick={() => onConfirm([...checked])}
            disabled={checked.size === 0 || saving}
            className="flex-1 py-2.5 bg-slate-800 text-white rounded-xl text-sm font-medium disabled:opacity-50 flex items-center justify-center gap-1.5"
          >
            {saving && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            Mark {checked.size} as used
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Recipe card ─────────────────────────────────────────────────────────────

function RecipeCard({ recipe, onDelete, showMissing, onMarkCooked }) {
  const [open, setOpen]       = useState(false)
  const [marking, setMarking] = useState(false)
  const [saving, setSaving]   = useState(false)
  const chip = urgencyChip(recipe.urgency_score)

  async function handleConfirm(names) {
    setSaving(true)
    await onMarkCooked(names)
    setSaving(false)
    setMarking(false)
  }

  return (
    <>
      <div className={`bg-white rounded-xl border border-slate-200 overflow-hidden ${urgencyBorder(recipe.urgency_score)}`}>
        <div className="px-4 py-3">
          {/* Name + delete */}
          <div className="flex items-start gap-2">
            <p className="flex-1 font-medium text-slate-800 text-sm leading-snug">{recipe.name}</p>
            <button onClick={() => onDelete(recipe.id)} className="text-slate-300 active:text-red-400 shrink-0 p-0.5 mt-0.5">
              <Trash2 className="w-4 h-4" />
            </button>
          </div>

          {/* Chips row */}
          <div className="flex flex-wrap gap-1.5 mt-1.5">
            {recipe.difficulty && (
              <span className={`text-xs px-2 py-0.5 rounded-full font-medium capitalize ${diffColor(recipe.difficulty)}`}>
                {recipe.difficulty}
              </span>
            )}
            {recipe.prep_time && (
              <span className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full">{fmtTime(recipe.prep_time)}</span>
            )}
            {chip && (
              <span className={`text-xs px-2 py-0.5 rounded-full ${chip.cls}`}>{chip.text}</span>
            )}
          </div>

          {/* Expiring ingredient chips */}
          {recipe.expiring_ingredients?.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {recipe.expiring_ingredients.map(e => (
                <span key={e.name} className={`text-xs px-2 py-0.5 rounded-full capitalize ${expiryChipCls(e.days_left)}`}>
                  {e.name} {e.days_left < 0 ? 'expired' : e.days_left === 0 ? 'today' : `in ${e.days_left}d`}
                </span>
              ))}
            </div>
          )}

          {/* Missing required — can_shop tab */}
          {showMissing && recipe.missing_required?.length > 0 && (
            <div className="mt-2 bg-slate-50 rounded-lg px-3 py-2">
              <p className="text-xs text-slate-500">
                <span className="font-medium">Need to buy: </span>
                <span className="capitalize">{recipe.missing_required.join(', ')}</span>
              </p>
            </div>
          )}

          {/* Have ingredients — collapsible */}
          {recipe.have?.length > 0 && (
            <>
              <button
                onClick={() => setOpen(o => !o)}
                className="flex items-center gap-1 mt-2 text-xs text-slate-400 active:text-slate-600"
              >
                {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                {open ? 'Hide' : `${recipe.have.length} ingredient${recipe.have.length !== 1 ? 's' : ''}`}
              </button>
              {open && (
                <p className="text-xs text-slate-500 mt-1 leading-relaxed capitalize">{recipe.have.join(', ')}</p>
              )}
            </>
          )}

          {/* Mark Cooked — only on can_cook tab */}
          {!showMissing && recipe.have?.length > 0 && (
            <button
              onClick={() => setMarking(true)}
              className="mt-3 w-full py-2 bg-slate-800 text-white rounded-xl text-xs font-medium flex items-center justify-center gap-1.5 active:bg-slate-700"
            >
              <CheckSquare className="w-3.5 h-3.5" />
              Mark Cooked
            </button>
          )}
        </div>
      </div>

      {marking && (
        <MarkCookedModal
          recipe={recipe}
          saving={saving}
          onConfirm={handleConfirm}
          onCancel={() => setMarking(false)}
        />
      )}
    </>
  )
}

// ─── Add / Import form ───────────────────────────────────────────────────────

function AddForm({ onSave, onCancel }) {
  const [name, setName]           = useState('')
  const [instructions, setInstr]  = useState('')
  const [difficulty, setDiff]     = useState('')
  const [prepTime, setPrep]       = useState('')
  const [source, setSource]       = useState('')
  const [ingInput, setIngInput]   = useState('')
  const [ingredients, setIngs]    = useState([])
  const [saving, setSaving]       = useState(false)
  const [error, setError]         = useState(null)

  const [importUrl, setImportUrl]     = useState('')
  const [importing, setImporting]     = useState(false)
  const [importError, setImportError] = useState(null)

  async function handleImport() {
    const url = importUrl.trim()
    if (!url) return
    setImporting(true); setImportError(null)
    try {
      const data = await parseRecipeUrl(url)
      setName(data.name || '')
      setInstr(data.instructions || '')
      setDiff(data.difficulty ? data.difficulty.charAt(0).toUpperCase() + data.difficulty.slice(1) : '')
      setPrep(data.prep_time || '')
      setSource(data.source || url)
      setIngs((data.ingredients || []).map(i => ({ name: i.name, is_optional: !!i.is_optional })))
      setImportUrl('')
    } catch (e) {
      setImportError(e.message)
    } finally {
      setImporting(false)
    }
  }

  function addIng() {
    const n = ingInput.trim().toLowerCase()
    if (!n || ingredients.find(i => i.name === n)) { setIngInput(''); return }
    setIngs(prev => [...prev, { name: n, is_optional: false }])
    setIngInput('')
  }

  function toggleOptional(name) {
    setIngs(prev => prev.map(i => i.name === name ? { ...i, is_optional: !i.is_optional } : i))
  }

  function removeIng(name) {
    setIngs(prev => prev.filter(i => i.name !== name))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!name.trim() || !instructions.trim()) return
    setSaving(true); setError(null)
    try {
      await createRecipe({ name: name.trim(), instructions: instructions.trim(), difficulty: difficulty || null, prep_time: prepTime || null, source: source || null, ingredients })
      onSave()
    } catch (e) { setError(e.message); setSaving(false) }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 p-4">

      {/* URL import */}
      <div className="bg-slate-50 rounded-xl border border-slate-200 p-3">
        <p className="text-xs text-slate-500 font-medium mb-2 flex items-center gap-1">
          <Link className="w-3 h-3" /> Import from URL or YouTube
        </p>
        <div className="flex gap-2">
          <input
            value={importUrl}
            onChange={e => setImportUrl(e.target.value)}
            placeholder="https://... or YouTube link"
            className="flex-1 text-xs border border-slate-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:border-orange-300"
          />
          <button
            type="button"
            onClick={handleImport}
            disabled={importing || !importUrl.trim()}
            className="px-3 py-2 bg-slate-700 text-white rounded-xl text-xs font-medium disabled:opacity-50 flex items-center gap-1"
          >
            {importing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Import'}
          </button>
        </div>
        {importError && <p className="text-xs text-red-500 mt-1">{importError}</p>}
      </div>

      <div>
        <label className="text-xs text-slate-500 block mb-1">Recipe name *</label>
        <input
          value={name} onChange={e => setName(e.target.value)}
          placeholder="e.g. Nasi Goreng"
          className="w-full text-sm border border-slate-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:border-orange-300"
          required
        />
      </div>

      <div>
        <label className="text-xs text-slate-500 block mb-1">Instructions *</label>
        <textarea
          value={instructions} onChange={e => setInstr(e.target.value)}
          placeholder="Steps to cook…"
          rows={4}
          className="w-full text-sm border border-slate-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:border-orange-300 resize-none"
          required
        />
      </div>

      <div className="flex gap-2">
        <div className="flex-1">
          <label className="text-xs text-slate-500 block mb-1">Difficulty</label>
          <select value={difficulty} onChange={e => setDiff(e.target.value)}
            className="w-full text-sm border border-slate-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:border-orange-300 text-slate-700">
            <option value="">—</option>
            <option>Easy</option><option>Medium</option><option>Hard</option>
          </select>
        </div>
        <div className="flex-1">
          <label className="text-xs text-slate-500 block mb-1">Prep time</label>
          <select value={prepTime} onChange={e => setPrep(e.target.value)}
            className="w-full text-sm border border-slate-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:border-orange-300 text-slate-700">
            <option value="">—</option>
            <option value="under_10">&lt;10 mins</option>
            <option value="10_to_20">10-20 mins</option>
            <option value="over_20">20+ mins</option>
          </select>
        </div>
      </div>

      <div>
        <label className="text-xs text-slate-500 block mb-1">Ingredients</label>
        <div className="flex gap-2">
          <input
            value={ingInput} onChange={e => setIngInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addIng())}
            placeholder="e.g. garlic"
            className="flex-1 text-sm border border-slate-200 rounded-xl px-3 py-2 bg-white focus:outline-none focus:border-orange-300"
          />
          <button type="button" onClick={addIng} className="px-3 py-2 bg-orange-500 text-white rounded-xl text-sm font-medium active:bg-orange-600">Add</button>
        </div>
        {ingredients.length > 0 && (
          <div className="flex flex-col gap-1.5 mt-2">
            {ingredients.map(ing => (
              <div key={ing.name} className="flex items-center gap-2 bg-slate-50 rounded-lg px-3 py-2">
                <span className="flex-1 text-sm text-slate-700 capitalize">{ing.name}</span>
                <button type="button" onClick={() => toggleOptional(ing.name)}
                  className={`text-xs px-2 py-0.5 rounded-full border transition-colors ${ing.is_optional ? 'border-slate-300 text-slate-400' : 'border-orange-300 text-orange-500 bg-orange-50'}`}>
                  {ing.is_optional ? 'optional' : 'required'}
                </button>
                <button type="button" onClick={() => removeIng(ing.name)} className="text-slate-300 active:text-red-400">
                  <X className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}

      <div className="flex gap-2 pt-1">
        <button type="button" onClick={onCancel} className="flex-1 py-2.5 border border-slate-200 rounded-xl text-sm text-slate-600 active:bg-slate-50">Cancel</button>
        <button type="submit" disabled={saving}
          className="flex-1 py-2.5 bg-orange-500 text-white rounded-xl text-sm font-medium active:bg-orange-600 disabled:opacity-50 flex items-center justify-center gap-1">
          {saving && <Loader2 className="w-4 h-4 animate-spin" />}
          Save recipe
        </button>
      </div>
    </form>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────


export default function RecipesPage() {
  const [data, setData]         = useState({ can_cook: [], can_shop: [] })
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [tab, setTab]           = useState('can_cook')
  const [phase, setPhase]       = useState('list')
  const [diffFilter, setDiffFilter] = useState('')
  const [timeFilter, setTimeFilter] = useState('')

  async function load() {
    setLoading(true); setError(null)
    try { setData(await getRecipes()) }
    catch (e) { setError(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  async function handleDelete(id) {
    setData(prev => ({
      can_cook: prev.can_cook.filter(r => r.id !== id),
      can_shop: prev.can_shop.filter(r => r.id !== id),
    }))
    await deleteRecipe(id).catch(load)
  }

  async function handleMarkCooked(names) {
    await markUsed(names)
    await load()
  }

  function applyFilters(list) {
    return list.filter(r => {
      if (diffFilter && (r.difficulty || '').toLowerCase() !== diffFilter) return false
      if (timeFilter && r.prep_time !== timeFilter) return false
      return true
    })
  }

  if (phase === 'add') {
    return (
      <div>
        <div className="flex items-center gap-3 px-4 py-2.5 bg-white border-b border-slate-100">
          <button onClick={() => setPhase('list')} className="text-slate-400 active:text-slate-600 p-0.5">
            <X className="w-5 h-5" />
          </button>
          <span className="text-sm font-medium text-slate-700">New recipe</span>
        </div>
        <AddForm onSave={() => { setPhase('list'); load() }} onCancel={() => setPhase('list')} />
      </div>
    )
  }

  const allCook = data.can_cook ?? []
  const allShop = data.can_shop ?? []
  const recipes = applyFilters(tab === 'can_cook' ? allCook : allShop)

  return (
    <>
      {/* Sub-header: tabs + actions */}
      <div className="bg-white border-b border-slate-100 sticky top-0 z-10">
        <div className="flex items-center justify-between px-4 py-2">
          <div className="flex gap-1">
            {['can_cook', 'can_shop'].map(t => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${tab === t ? 'bg-orange-500 text-white' : 'text-slate-500 active:bg-slate-100'}`}>
                {t === 'can_cook' ? `Can cook (${allCook.length})` : `Need to shop (${allShop.length})`}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <button onClick={load} className="text-slate-400 p-1 active:text-slate-600"><RefreshCw className="w-4 h-4" /></button>
            <button onClick={() => setPhase('add')} className="text-orange-500 p-1 active:text-orange-600"><Plus className="w-5 h-5" /></button>
          </div>
        </div>

        {/* Difficulty + time filters */}
        <div className="flex gap-2 px-4 pb-2.5">
          <select
            value={diffFilter}
            onChange={e => setDiffFilter(e.target.value)}
            className="flex-1 text-xs border border-slate-200 rounded-xl px-3 py-1.5 bg-white focus:outline-none focus:border-orange-300 text-slate-600"
          >
            <option value="">All difficulties</option>
            <option value="easy">Easy</option>
            <option value="medium">Medium</option>
            <option value="hard">Hard</option>
          </select>
          <select
            value={timeFilter}
            onChange={e => setTimeFilter(e.target.value)}
            className="flex-1 text-xs border border-slate-200 rounded-xl px-3 py-1.5 bg-white focus:outline-none focus:border-orange-300 text-slate-600"
          >
            <option value="">All times</option>
            <option value="under_10">&lt;10 mins</option>
            <option value="10_to_20">10-20 mins</option>
            <option value="over_20">20+ mins</option>
          </select>
        </div>
      </div>

      {/* Expiry notification bar */}
      {!loading && allCook.length > 0 && <ExpiryBar recipes={allCook} />}

      {loading && (
        <div className="flex-1 flex items-center justify-center min-h-48">
          <Loader2 className="w-8 h-8 text-orange-400 animate-spin" />
        </div>
      )}

      {error && (
        <div className="m-4 bg-red-50 text-red-700 text-sm px-4 py-3 rounded-xl border border-red-200">{error}</div>
      )}

      {!loading && recipes.length === 0 && (
        <div className="flex-1 flex flex-col items-center justify-center gap-1 min-h-48 text-slate-400">
          <p className="text-sm">
            {diffFilter || timeFilter
              ? 'No recipes match the filter'
              : tab === 'can_cook' ? 'No recipes you can cook right now' : 'Nothing to shop for'}
          </p>
          {tab === 'can_cook' && !diffFilter && !timeFilter && (
            <button onClick={() => setPhase('add')} className="text-xs text-orange-500 mt-1">+ Add a recipe</button>
          )}
        </div>
      )}

      {!loading && (
        <div className="flex flex-col gap-2 p-4">
          {recipes.map(r => (
            <RecipeCard
              key={r.id}
              recipe={r}
              onDelete={handleDelete}
              showMissing={tab === 'can_shop'}
              onMarkCooked={handleMarkCooked}
            />
          ))}
        </div>
      )}
    </>
  )
}
