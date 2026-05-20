import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL

export default function Register() {
  const [form,    setForm]    = useState({ username: '', email: '', password: '' })
  const [error,   setError]   = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await axios.post(`${API}/register`, form)
      navigate('/login')
    } catch (err) {
      setError(err.response?.data?.error || 'registration failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-[calc(100vh-56px)] px-4">
      <div className="w-full max-w-sm animate-slide-up">

        <div className="mb-8">
          <h1 className="text-2xl font-bold tracking-tight mb-1">Create account</h1>
          <p className="text-gray-500 text-sm">Join simuxjudge and start solving</p>
        </div>

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

        <form onSubmit={handleSubmit} className="space-y-4">
          {[
            { key: 'username', label: 'Username',        type: 'text',     ph: 'tfm4n' },
            { key: 'email',    label: 'Email',           type: 'email',    ph: 'you@example.com' },
            { key: 'password', label: 'Password',        type: 'password', ph: '••••••••' },
          ].map(({ key, label, type, ph }) => (
            <div key={key}>
              <label className="block text-xs font-medium text-gray-400 uppercase tracking-wider mb-2">
                {label}
              </label>
              <input
                type={type}
                value={form[key]}
                onChange={e => setForm({ ...form, [key]: e.target.value })}
                placeholder={ph}
                className="w-full bg-card border border-border rounded-lg px-4 py-3 text-sm text-white placeholder-gray-600
                           focus:outline-none focus:border-red-600 transition-colors font-mono"
              />
            </div>
          ))}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed
                       text-white font-semibold py-3 rounded-lg transition-colors text-sm mt-2"
          >
            {loading ? 'Creating account...' : 'Create Account'}
          </button>
        </form>

        <p className="text-center text-gray-600 text-sm mt-6">
          Have an account?{' '}
          <Link to="/login" className="text-red-500 hover:text-red-400 font-medium transition-colors">
            Login
          </Link>
        </p>
      </div>
    </div>
  )
}