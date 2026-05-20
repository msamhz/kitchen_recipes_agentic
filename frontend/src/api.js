const BASE = import.meta.env.VITE_API_URL

export async function scanImages(files) {
  const form = new FormData()
  files.forEach(f => form.append('files', f))
  const res = await fetch(`${BASE}/scan`, { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Scan failed (${res.status})`)
  return res.json()
}

export async function upsertStock(names, mode = 'restock', metadata = {}) {
  const res = await fetch(`${BASE}/stock/upsert`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ names, mode, metadata }),
  })
  if (!res.ok) throw new Error(`Save failed (${res.status})`)
  return res.json()
}

export async function getStock() {
  const res = await fetch(`${BASE}/stock`)
  if (!res.ok) throw new Error(`Failed to load stock (${res.status})`)
  return res.json()
}

export async function patchStock(id, updates) {
  const res = await fetch(`${BASE}/stock/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw new Error(`Update failed (${res.status})`)
  return res.json()
}

export async function deleteStock(id) {
  const res = await fetch(`${BASE}/stock/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete failed (${res.status})`)
  return res.json()
}

export async function getRecipes() {
  const res = await fetch(`${BASE}/recipes`)
  if (!res.ok) throw new Error(`Failed to load recipes (${res.status})`)
  return res.json()
}

export async function createRecipe(body) {
  const res = await fetch(`${BASE}/recipes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`Create recipe failed (${res.status})`)
  return res.json()
}

export async function deleteRecipe(id) {
  const res = await fetch(`${BASE}/recipes/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete recipe failed (${res.status})`)
  return res.json()
}

export async function getShoppingList() {
  const res = await fetch(`${BASE}/recipes/shopping-list`)
  if (!res.ok) throw new Error(`Failed to load shopping list (${res.status})`)
  return res.json()
}

export async function markUsed(names) {
  const res = await fetch(`${BASE}/stock/mark-used`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ names }),
  })
  if (!res.ok) throw new Error(`Mark used failed (${res.status})`)
  return res.json()
}

export async function parseRecipeUrl(url) {
  const res = await fetch(`${BASE}/recipes/parse-url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Parse failed (${res.status})`)
  }
  return res.json()
}
