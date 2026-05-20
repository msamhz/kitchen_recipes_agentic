import { useState, useEffect } from 'react'
import { Loader2, RefreshCw, ShoppingCart, Check } from 'lucide-react'
import { getShoppingList, upsertStock } from '../api'

function buildItems(pairs, selectedRecipeIds) {
  const filtered = pairs.filter(p => selectedRecipeIds.has(p.recipe_id))
  const map = {}
  for (const p of filtered) {
    if (!map[p.ingredient]) map[p.ingredient] = []
    if (!map[p.ingredient].includes(p.recipe_name)) map[p.ingredient].push(p.recipe_name)
  }
  return Object.entries(map)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([ingredient, needed_for]) => ({ ingredient, needed_for }))
}

export default function ShoppingPage() {
  const [pairs, setPairs]               = useState([])
  const [recipes, setRecipes]           = useState([])
  const [selectedRecipes, setSelected]  = useState(new Set())
  const [cart, setCart]                 = useState(new Set())
  const [loading, setLoading]           = useState(true)
  const [buying, setBuying]             = useState(false)
  const [done, setDone]                 = useState([])

  async function load() {
    setLoading(true)
    try {
      const data = await getShoppingList()
      // only show recipes that actually have missing ingredients
      const withMissing = new Set(data.pairs.map(p => p.recipe_id))
      const shopRecipes = data.recipes.filter(r => withMissing.has(r.id))
      setPairs(data.pairs)
      setRecipes(shopRecipes)
      setSelected(new Set(shopRecipes.map(r => r.id)))
      setCart(new Set())
      setDone([])
    } catch { /* silent */ }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  function toggleRecipe(id) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  function toggleCart(ingredient) {
    setCart(prev => {
      const next = new Set(prev)
      next.has(ingredient) ? next.delete(ingredient) : next.add(ingredient)
      return next
    })
  }

  async function handleBuy() {
    if (cart.size === 0) return
    setBuying(true)
    try {
      await upsertStock([...cart], 'restock', {})
      setDone([...cart])
      setCart(new Set())
      await load()
    } catch { /* silent */ }
    finally { setBuying(false) }
  }

  const allItems  = buildItems(pairs, selectedRecipes)
  const toBuy     = allItems.filter(i => !cart.has(i.ingredient))
  const inCart    = allItems.filter(i => cart.has(i.ingredient))

  return (
    <>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-white border-b border-slate-100">
        <div className="flex items-center gap-2">
          <ShoppingCart className="w-4 h-4 text-orange-500" />
          <span className="text-sm font-medium text-slate-700">Shopping List</span>
          {allItems.length > 0 && (
            <span className="text-xs bg-orange-100 text-orange-600 px-2 py-0.5 rounded-full">{allItems.length} item{allItems.length !== 1 ? 's' : ''}</span>
          )}
        </div>
        <button onClick={load} className="text-slate-400 p-1 active:text-slate-600">
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {loading ? (
        <div className="flex-1 flex items-center justify-center min-h-48">
          <Loader2 className="w-8 h-8 text-orange-400 animate-spin" />
        </div>
      ) : (
        <div className="flex flex-col gap-3 p-4">

          {/* Success banner */}
          {done.length > 0 && (
            <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-3 flex items-center gap-2">
              <Check className="w-4 h-4 text-green-500 shrink-0" />
              <p className="text-sm text-green-700">
                Added to pantry: <span className="capitalize">{done.join(', ')}</span>
              </p>
            </div>
          )}

          {/* No recipes with missing items */}
          {recipes.length === 0 && (
            <div className="flex-1 flex flex-col items-center justify-center gap-1 min-h-48 text-slate-400">
              <ShoppingCart className="w-8 h-8 text-slate-300" />
              <p className="text-sm mt-2">Nothing to shop for</p>
              <p className="text-xs">All recipe ingredients are in stock</p>
            </div>
          )}

          {/* Recipe filter */}
          {recipes.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <p className="text-xs font-medium text-slate-500 mb-2.5">Shopping for</p>
              <div className="flex flex-wrap gap-1.5">
                {recipes.map(r => (
                  <button
                    key={r.id}
                    onClick={() => toggleRecipe(r.id)}
                    className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                      selectedRecipes.has(r.id)
                        ? 'bg-orange-500 border-orange-500 text-white'
                        : 'border-slate-200 text-slate-500 bg-slate-50'
                    }`}
                  >
                    {r.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* To buy list */}
          {toBuy.length > 0 && (
            <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
              <p className="text-xs font-medium text-slate-500 px-4 pt-3 pb-2">To buy · tap to add to cart</p>
              <div className="flex flex-col">
                {toBuy.map(item => (
                  <button
                    key={item.ingredient}
                    onClick={() => toggleCart(item.ingredient)}
                    className="flex items-center gap-3 px-4 py-3 border-t border-slate-50 active:bg-slate-50 text-left"
                  >
                    <div className="w-5 h-5 rounded-full border-2 border-slate-300 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-slate-700 capitalize">{item.ingredient}</p>
                      <p className="text-xs text-slate-400 truncate">for: {item.needed_for.join(', ')}</p>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Cart */}
          {inCart.length > 0 && (
            <div className="bg-white rounded-xl border border-orange-200 overflow-hidden">
              <p className="text-xs font-medium text-orange-600 px-4 pt-3 pb-2">In cart · tap to remove</p>
              <div className="flex flex-col">
                {inCart.map(item => (
                  <button
                    key={item.ingredient}
                    onClick={() => toggleCart(item.ingredient)}
                    className="flex items-center gap-3 px-4 py-3 border-t border-slate-50 active:bg-orange-50 text-left"
                  >
                    <div className="w-5 h-5 rounded-full bg-orange-400 border-2 border-orange-400 flex items-center justify-center shrink-0">
                      <Check className="w-3 h-3 text-white" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-slate-500 capitalize line-through">{item.ingredient}</p>
                      <p className="text-xs text-slate-400 truncate">for: {item.needed_for.join(', ')}</p>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Empty state after filtering */}
          {recipes.length > 0 && allItems.length === 0 && (
            <p className="text-sm text-slate-400 text-center py-4">
              {selectedRecipes.size === 0 ? 'Select a recipe above to see what to buy' : 'Nothing to buy for selected recipes'}
            </p>
          )}

        </div>
      )}

      {/* Sticky buy button */}
      {inCart.size > 0 && (
        <div className="sticky bottom-0 -mx-0 px-4 pb-4 pt-2 bg-gradient-to-t from-slate-50">
          <button
            onClick={handleBuy}
            disabled={buying}
            className="w-full py-3 bg-orange-500 text-white rounded-xl font-medium text-sm active:bg-orange-600 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {buying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
            Mark {inCart.size} item{inCart.size !== 1 ? 's' : ''} as bought
          </button>
        </div>
      )}
    </>
  )
}
