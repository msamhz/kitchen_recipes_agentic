import { useState } from 'react'
import ScanPage     from './pages/ScanPage'
import StockPage    from './pages/StockPage'
import RecipesPage  from './pages/RecipesPage'
import ShoppingPage from './pages/ShoppingPage'
import TabBar       from './components/TabBar'

const TAB_LABELS = { scan: 'Scan', stock: 'Pantry', recipes: 'Recipes', shopping: 'Shopping' }

export default function App() {
  const [tab, setTab] = useState('scan')

  return (
    <div className="flex flex-col h-screen max-w-md mx-auto bg-slate-50">
      <header className="bg-white border-b border-slate-200 px-4 py-3 flex items-center justify-between shrink-0 z-10">
        <span className="text-lg font-semibold text-slate-800">Kitchen</span>
        <span className="text-sm font-medium text-orange-500">{TAB_LABELS[tab]}</span>
      </header>

      <div className="flex-1 overflow-y-auto pb-20 flex flex-col min-h-0">
        {tab === 'scan'     && <ScanPage />}
        {tab === 'stock'    && <StockPage />}
        {tab === 'recipes'  && <RecipesPage />}
        {tab === 'shopping' && <ShoppingPage />}
      </div>

      <TabBar current={tab} onChange={setTab} />
    </div>
  )
}
