import { useEffect, useState } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import Editor from '@monaco-editor/react'
import axios from 'axios'

const API = 'http://localhost:3000'

const LANGS = ['python', 'cpp', 'c', 'java', 'javascript', 'rust']

const MONACO_LANG = {
  python: 'python', cpp: 'cpp', c: 'c',
  java: 'java', javascript: 'javascript', rust: 'rust',
}

const STARTER = {
  python:     'n = int(input())\n# your code here\n',
  cpp:        '#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    // your code here\n    return 0;\n}\n',
  c:          '#include <stdio.h>\n\nint main() {\n    // your code here\n    return 0;\n}\n',
  java:       'import java.util.Scanner;\n\npublic class Main {\n    public static void main(String[] args) {\n        Scanner sc = new Scanner(System.in);\n        // your code here\n    }\n}\n',
  javascript: 'const lines = require("fs").readFileSync("/dev/stdin","utf8").trim().split("\\n");\n// your code here\n',
  rust:       'use std::io::{self, BufRead};\n\nfn main() {\n    let stdin = io::stdin();\n    // your code here\n}\n',
}

const DIFF_COLOR = {
  easy: 'text-emerald-400', medium: 'text-amber-400', hard: 'text-red-400',
}

export default function Problem() {
  const { slug }      = useParams()
  const navigate      = useNavigate()
  const [problem,     setProblem]     = useState(null)
  const [language,    setLanguage]    = useState('python')
  const [code,        setCode]        = useState(STARTER['python'])
  const [loading,     setLoading]     = useState(true)
  const [submitting,  setSubmitting]  = useState(false)
  const [error,       setError]       = useState('')

  useEffect(() => {
    axios.get(`${API}/problems/${slug}`)
      .then(r => setProblem(r.data))
      .catch(() => navigate('/problems'))
      .finally(() => setLoading(false))
  }, [slug])

  function handleLangChange(lang) {
    setLanguage(lang)
    setCode(STARTER[lang])
  }

  async function handleSubmit() {
    const token = localStorage.getItem('token')
    if (!token) return navigate('/login')
    setSubmitting(true)
    setError('')
    try {
      const res = await axios.post(
        `${API}/submit`,
        { problem_slug: slug, language, code },
        { headers: { Authorization: `Bearer ${token}` } }
      )
      navigate(`/verdict/${res.data.id}`)
    } catch (err) {
      setError(err.response?.data?.error || 'submission failed')
      setSubmitting(false)
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="flex gap-1">
        {[0,1,2].map(i => (
          <span key={i} className="w-2 h-2 rounded-full bg-red-600 animate-bounce"
            style={{ animationDelay: `${i*0.15}s` }} />
        ))}
      </div>
    </div>
  )

  if (!problem) return null

  return (
    <div className="flex h-[calc(100vh-56px)] animate-fade-in">

      {/* ── LEFT: Problem statement ── */}
      <div className="w-[400px] flex-shrink-0 flex flex-col border-r border-border bg-bg overflow-hidden">

        {/* Problem header */}
        <div className="px-6 pt-6 pb-4 border-b border-border flex-shrink-0">
          <div className="flex items-start justify-between gap-3 mb-3">
            <h1 className="text-lg font-bold tracking-tight leading-snug">{problem.title}</h1>
            <span className={`text-xs font-semibold flex-shrink-0 mt-0.5 ${DIFF_COLOR[problem.difficulty] || 'text-amber-400'}`}>
              {problem.difficulty}
            </span>
          </div>
          <div className="flex gap-4 text-xs text-gray-600 font-mono">
            <span>⏱ {problem.time_limit}ms</span>
            <span>💾 {problem.mem_limit}MB</span>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-6">
          <div>
            <p className="text-gray-300 text-sm leading-relaxed">{problem.description}</p>
          </div>

          {problem.sample_cases?.length > 0 && (
            <div>
              <h2 className="text-[11px] font-semibold uppercase tracking-widest text-gray-600 mb-3">
                Sample Cases
              </h2>
              <div className="space-y-3">
                {problem.sample_cases.map((tc, i) => (
                  <div key={i} className="rounded-lg border border-border overflow-hidden">
                    <div className="grid grid-cols-2 divide-x divide-border">
                      <div className="p-3">
                        <div className="text-[10px] uppercase tracking-wider text-gray-600 mb-2 font-semibold">Input</div>
                        <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap">{tc.input}</pre>
                      </div>
                      <div className="p-3">
                        <div className="text-[10px] uppercase tracking-wider text-gray-600 mb-2 font-semibold">Output</div>
                        <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap">{tc.expected_output}</pre>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── RIGHT: Editor ── */}
      <div className="flex-1 flex flex-col bg-[#0f0f0f] min-w-0">

        {/* Toolbar */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-surface flex-shrink-0">

          {/* Language pills */}
          <div className="flex gap-1 flex-wrap">
            {LANGS.map(lang => (
              <button
                key={lang}
                onClick={() => handleLangChange(lang)}
                className={`px-3 py-1 rounded text-xs font-mono font-medium transition-all ${
                  language === lang
                    ? 'bg-red-600 text-white shadow-sm shadow-red-900'
                    : 'text-gray-500 hover:text-gray-300 hover:bg-white/5'
                }`}
              >
                {lang}
              </button>
            ))}
          </div>

          {/* Submit */}
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className={`flex items-center gap-2 px-5 py-1.5 rounded-md text-sm font-semibold transition-all ${
              submitting
                ? 'bg-red-800/50 text-red-400 cursor-not-allowed'
                : 'bg-red-600 hover:bg-red-500 text-white'
            }`}
          >
            {submitting ? (
              <>
                <svg className="animate-spin w-3.5 h-3.5" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                </svg>
                Submitting
              </>
            ) : (
              <>
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                  <path d="M2 6h8M6 2l4 4-4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
                Submit
              </>
            )}
          </button>
        </div>

        {/* Error bar */}
        {error && (
          <div className="mx-4 mt-3 flex items-center gap-2 text-sm text-red-400 bg-red-900/20 border border-red-900 rounded-lg px-4 py-2 flex-shrink-0">
            <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
              <circle cx="7" cy="7" r="6" stroke="#f87171" strokeWidth="1.5"/>
              <path d="M7 4v3" stroke="#f87171" strokeWidth="1.5" strokeLinecap="round"/>
              <circle cx="7" cy="10" r="0.8" fill="#f87171"/>
            </svg>
            {error}
          </div>
        )}

        {/* Monaco */}
        <div className="flex-1 min-h-0">
          <Editor
            height="100%"
            language={MONACO_LANG[language]}
            value={code}
            onChange={val => setCode(val || '')}
            theme="vs-dark"
            options={{
              fontSize: 13.5,
              fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
              fontLigatures: true,
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              lineNumbers: 'on',
              renderLineHighlight: 'line',
              padding: { top: 20, bottom: 20 },
              smoothScrolling: true,
              cursorBlinking: 'smooth',
              cursorSmoothCaretAnimation: 'on',
              bracketPairColorization: { enabled: true },
              overviewRulerLanes: 0,
              hideCursorInOverviewRuler: true,
              scrollbar: {
                verticalScrollbarSize: 4,
                horizontalScrollbarSize: 4,
              },
            }}
          />
        </div>
      </div>
    </div>
  )
}