import { Camera, Package, BookOpen, ShoppingCart } from 'lucide-react'

const TABS = [
  { id: 'scan',     label: 'Scan',     Icon: Camera },
  { id: 'stock',    label: 'Pantry',   Icon: Package },
  { id: 'recipes',  label: 'Recipes',  Icon: BookOpen },
  { id: 'shopping', label: 'Shopping', Icon: ShoppingCart },
]

export default function TabBar({ current, onChange }) {
  return (
    <nav
      className="fixed bottom-0 left-0 right-0 max-w-md mx-auto bg-white border-t border-slate-200 flex z-20"
      style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
    >
      {TABS.map(({ id, label, Icon }) => {
        const active = current === id
        return (
          <button
            key={id}
            onClick={() => onChange(id)}
            className={`flex-1 flex flex-col items-center gap-1 py-2.5 transition-colors ${active ? 'text-orange-500' : 'text-slate-400'}`}
          >
            <Icon className="w-5 h-5" />
            <span className="text-xs font-medium">{label}</span>
          </button>
        )
      })}
    </nav>
  )
}
