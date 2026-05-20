import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL

const DIFF = {
  easy:   { label: 'Easy',   cls: 'text-emerald-400 bg-emerald-950/60 border-emerald-900' },
  medium: { label: 'Medium', cls: 'text-amber-400   bg-amber-950/60   border-amber-900'  },
  hard:   { label: 'Hard',   cls: 'text-red-400     bg-red-950/60     border-red-900'    },
}

// Status indicator for a problem row
// status: 'ac' | 'partial' | 'attempted' | null
function StatusDot({ status }) {
  if (!status) return <span className="w-2 h-2" />
  const cfg = {
    ac:        { cls: 'bg-emerald-500', title: 'Accepted' },
    partial:   { cls: 'bg-amber-500',   title: 'Partial'  },
    attempted: { cls: 'bg-red-500',     title: 'Attempted' },
  }
  const c = cfg[status]
  return (
    <span
      className={`w-2 h-2 rounded-full inline-block flex-shrink-0 ${c.cls}`}
      title={c.title}
    />
  )
}

export default function Problems() {
  const [problems, setProblems] = useState([])
  const [statuses, setStatuses] = useState({}) // slug -> 'ac' | 'partial' | 'attempted'
  const [loading,  setLoading]  = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('token')

    axios.get(`${API}/problems`)
      .then(async r => {
        setProblems(r.data)

        // Fetch per-problem status if logged in
        if (token) {
          try {
            const res = await axios.get(`${API}/my-statuses`, {
              headers: { Authorization: `Bearer ${token}` }
            })
            // Expects: { statuses: { slug: 'ac'|'partial'|'attempted' } }
            setStatuses(res.data.statuses || {})
          } catch {
            // Endpoint may not exist yet; silently ignore
          }
        }
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="flex gap-1">
        {[0,1,2].map(i => (
          <span
            key={i}
            className="w-2 h-2 rounded-full bg-red-600 animate-bounce"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  )

  return (
    <div className="max-w-5xl mx-auto px-6 py-10 animate-fade-in">

      {/* Header */}
      <div className="flex items-end justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Problems</h1>
          <p className="text-gray-500 text-sm mt-1 font-mono">
            {problems.length} problems available
          </p>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 text-[11px] text-gray-600 font-mono">
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" />Accepted</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-amber-500 inline-block" />Partial</span>
          <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-500 inline-block" />Attempted</span>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-xl border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface border-b border-border">
              <th className="text-left px-4 py-3 text-[11px] font-semibold uppercase tracking-widest text-gray-600 w-8"></th>
              <th className="text-left px-4 py-3 text-[11px] font-semibold uppercase tracking-widest text-gray-600 w-10">#</th>
              <th className="text-left px-4 py-3 text-[11px] font-semibold uppercase tracking-widest text-gray-600">Title</th>
              <th className="text-left px-4 py-3 text-[11px] font-semibold uppercase tracking-widest text-gray-600">Difficulty</th>
              <th className="text-left px-4 py-3 text-[11px] font-semibold uppercase tracking-widest text-gray-600">Time Limit</th>
            </tr>
          </thead>
          <tbody className="bg-bg divide-y divide-border">
            {problems.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-6 py-16 text-center text-gray-600">
                  No problems yet.
                </td>
              </tr>
            ) : problems.map((p, i) => {
              const diff   = DIFF[p.difficulty] || DIFF.medium
              const status = statuses[p.slug] || null
              const titleColor =
                status === 'ac'        ? 'text-emerald-400 group-hover:text-emerald-300' :
                status === 'partial'   ? 'text-amber-400   group-hover:text-amber-300'   :
                status === 'attempted' ? 'text-red-400     group-hover:text-red-300'     :
                'text-gray-200 group-hover:text-red-400'

              return (
                <tr key={p.id} className="group hover:bg-surface transition-colors">
                  <td className="px-4 py-4">
                    <StatusDot status={status} />
                  </td>
                  <td className="px-4 py-4 text-gray-600 font-mono text-xs">{i + 1}</td>
                  <td className="px-4 py-4">
                    <Link
                      to={`/problems/${p.slug}`}
                      className={`font-medium transition-colors ${titleColor}`}
                    >
                      {p.title}
                    </Link>
                  </td>
                  <td className="px-4 py-4">
                    <span className={`text-[11px] font-semibold px-2.5 py-1 rounded-full border ${diff.cls}`}>
                      {diff.label}
                    </span>
                  </td>
                  <td className="px-4 py-4 text-gray-500 font-mono text-xs">{p.time_limit}ms</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}