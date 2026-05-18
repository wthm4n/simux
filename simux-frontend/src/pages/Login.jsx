import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import axios from 'axios'

const API = 'http://localhost:3000'

export default function Login() {
  const [form,    setForm]    = useState({ username: '', password: '' })
  const [error,   setError]   = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await axios.post(`${API}/login`, form)
      localStorage.setItem('token',    res.data.token)
      localStorage.setItem('username', res.data.username)
      localStorage.setItem('role',     res.data.role)
      navigate('/problems')
    } catch (err) {
      setError(err.response?.data?.error || 'login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-[calc(100vh-56px)] px-4">
      <div className="w-full max-w-sm animate-slide-up">

        {/* Header */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold tracking-tight mb-1">Welcome back</h1>
          <p className="text-gray-500 text-sm">Sign in to continue judging</p>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 flex items-center gap-2 text-sm text-red-400 bg-red-900/20 border border-red-900 rounded-lg px-4 py-3">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="flex-shrink-0">
              <circle cx="7" cy="7" r="6" stroke="#f87171" strokeWidth="1.5"/>
              <path d="M7 4v3" stroke="#f87171" strokeWidth="1.5" strokeLinecap="round"/>
              <circle cx="7" cy="10" r="0.8" fill="#f87171"/>
            </svg>
            {error}
          </div>
        )}

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
              Username
            </label>
            <input
              autoFocus
              value={form.username}
              onChange={e => setForm({ ...form, username: e.target.value })}
              placeholder="tfm4n"
              className="w-full bg-card border border-border rounded-lg px-4 py-3 text-sm text-white placeholder-gray-600
                         focus:outline-none focus:border-red-600 focus:bg-card transition-colors font-mono"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
              Password
            </label>
            <input
              type="password"
              value={form.password}
              onChange={e => setForm({ ...form, password: e.target.value })}
              placeholder="••••••••"
              className="w-full bg-card border border-border rounded-lg px-4 py-3 text-sm text-white placeholder-gray-600
                         focus:outline-none focus:border-red-600 transition-colors font-mono"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed
                       text-white font-semibold py-3 rounded-lg transition-colors text-sm mt-2"
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
                Signing in...
              </span>
            ) : 'Sign In'}
          </button>
        </form>

        <p className="text-center text-gray-600 text-sm mt-6">
          No account?{' '}
          <Link to="/register" className="text-red-500 hover:text-red-400 font-medium transition-colors">
            Register
          </Link>
        </p>
      </div>
    </div>
  )
}