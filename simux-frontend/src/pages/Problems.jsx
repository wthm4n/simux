import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import axios from 'axios'

const API = 'http://localhost:3000'

const DIFF = {
  easy:   { label: 'Easy',   cls: 'text-emerald-400 bg-emerald-950/60 border-emerald-900' },
  medium: { label: 'Medium', cls: 'text-amber-400   bg-amber-950/60   border-amber-900'  },
  hard:   { label: 'Hard',   cls: 'text-red-400     bg-red-950/60     border-red-900'    },
}

export default function Problems() {
  const [problems, setProblems] = useState([])
  const [loading,  setLoading]  = useState(true)

  useEffect(() => {
    axios.get(`${API}/problems`)
      .then(r => setProblems(r.data))
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
      </div>

      {/* Table */}
      <div className="rounded-xl border border-border overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-surface border-b border-border">
              <th className="text-left px-6 py-3 text-[11px] font-semibold uppercase tracking-widest text-gray-600 w-12">#</th>
              <th className="text-left px-6 py-3 text-[11px] font-semibold uppercase tracking-widest text-gray-600">Title</th>
              <th className="text-left px-6 py-3 text-[11px] font-semibold uppercase tracking-widest text-gray-600">Difficulty</th>
              <th className="text-left px-6 py-3 text-[11px] font-semibold uppercase tracking-widest text-gray-600">Time Limit</th>
            </tr>
          </thead>
          <tbody className="bg-bg divide-y divide-border">
            {problems.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-6 py-16 text-center text-gray-600">
                  No problems yet.
                </td>
              </tr>
            ) : problems.map((p, i) => {
              const diff = DIFF[p.difficulty] || DIFF.medium
              return (
                <tr key={p.id} className="group hover:bg-surface transition-colors">
                  <td className="px-6 py-4 text-gray-600 font-mono text-xs">{i + 1}</td>
                  <td className="px-6 py-4">
                    <Link
                      to={`/problems/${p.slug}`}
                      className="font-medium text-gray-200 group-hover:text-red-400 transition-colors"
                    >
                      {p.title}
                    </Link>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`text-[11px] font-semibold px-2.5 py-1 rounded-full border ${diff.cls}`}>
                      {diff.label}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-gray-500 font-mono text-xs">{p.time_limit}ms</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}