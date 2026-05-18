import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
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

// Persists code per (slug, lang)
function getStoredCode(slug, lang) {
  try {
    const key = `code:${slug}:${lang}`
    return localStorage.getItem(key) || STARTER[lang]
  } catch { return STARTER[lang] }
}
function setStoredCode(slug, lang, code) {
  try { localStorage.setItem(`code:${slug}:${lang}`, code) } catch {}
}
function getStoredLang(slug) {
  try { return localStorage.getItem(`lang:${slug}`) || 'python' } catch { return 'python' }
}
function setStoredLang(slug, lang) {
  try { localStorage.setItem(`lang:${slug}`, lang) } catch {}
}

// ── Console line renderer ─────────────────────────────────────────────────────
function ConsoleLine({ line }) {
  const isErr = line.type === 'stderr'
  const isMeta = line.type === 'meta'
  return (
    <div className={`font-mono text-xs leading-5 whitespace-pre-wrap break-all ${
      isErr ? 'text-red-400' : isMeta ? 'text-gray-600' : 'text-gray-300'
    }`}>
      {line.text}
    </div>
  )
}

// ── Test case tile ────────────────────────────────────────────────────────────
function TCTile({ tc, idx, result }) {
  const [open, setOpen] = useState(false)

  // result: { passed: bool, time_ms: num } | null | 'hidden'
  const isHidden = !tc.is_sample
  const status = result === null ? 'pending'
    : result === 'hidden' ? 'hidden'
    : result?.passed ? 'pass'
    : result?.verdict === 'TLE' ? 'tle'
    : result?.verdict === 'RE' ? 're'
    : 'fail'

  const statusConfig = {
    pending: { dot: 'bg-gray-700',    ring: 'border-gray-800',   icon: null,            label: '—'    },
    pass:    { dot: 'bg-emerald-500', ring: 'border-emerald-800',icon: '✓',             label: 'Pass' },
    fail:    { dot: 'bg-red-500',     ring: 'border-red-900',    icon: '✗',             label: 'Fail' },
    tle:     { dot: 'bg-amber-500',   ring: 'border-amber-900',  icon: '⏱',            label: 'TLE'  },
    re:      { dot: 'bg-orange-500',  ring: 'border-orange-900', icon: '!',             label: 'RE'   },
    hidden:  { dot: 'bg-gray-600',    ring: 'border-gray-800',   icon: null,            label: '?'    },
  }

  const cfg = statusConfig[status]

  return (
    <div>
      <button
        onClick={() => setOpen(o => !o)}
        className={`w-full text-left rounded-lg border px-3 py-2.5 flex items-center gap-2.5 transition-all hover:bg-white/3 ${cfg.ring} bg-[#0a0a0a]`}
      >
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${cfg.dot}`} />
        <span className="text-xs text-gray-400 font-mono flex-1">
          Case {idx + 1}
          {isHidden && <span className="ml-1.5 text-[10px] text-gray-600 uppercase tracking-wider">hidden</span>}
        </span>
        {result?.time_ms > 0 && (
          <span className="text-[10px] text-gray-600 font-mono">{result.time_ms}ms</span>
        )}
        <span className={`text-xs font-bold font-mono ${
          status === 'pass' ? 'text-emerald-400' :
          status === 'fail' ? 'text-red-400' :
          status === 'tle'  ? 'text-amber-400' :
          status === 're'   ? 'text-orange-400' :
          'text-gray-600'
        }`}>
          {cfg.icon || cfg.label}
        </span>
        <svg
          className={`w-3 h-3 text-gray-700 transition-transform flex-shrink-0 ${open ? 'rotate-180' : ''}`}
          viewBox="0 0 12 12" fill="none"
        >
          <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
      </button>

      {open && (
        <div className="mt-1 rounded-lg border border-[#1a1a1a] overflow-hidden bg-[#080808]">
          {isHidden && status === 'hidden' ? (
            <div className="px-4 py-3 text-xs text-gray-600 italic font-mono">
              Hidden test case — not visible
            </div>
          ) : (
            <div className="grid grid-cols-2 divide-x divide-[#1a1a1a]">
              <div className="p-3">
                <div className="text-[9px] uppercase tracking-widest text-gray-600 mb-1.5 font-bold">Input</div>
                <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap break-all">
                  {isHidden ? <span className="text-gray-700 italic">hidden</span> : (tc.input || <span className="text-gray-700 italic">empty</span>)}
                </pre>
              </div>
              <div className="p-3">
                <div className="text-[9px] uppercase tracking-widest text-gray-600 mb-1.5 font-bold">Expected</div>
                <pre className="text-xs text-gray-300 font-mono whitespace-pre-wrap break-all">
                  {isHidden ? <span className="text-gray-700 italic">hidden</span> : (tc.expected_output || <span className="text-gray-700 italic">empty</span>)}
                </pre>
                {result?.actual_output && status !== 'pass' && (
                  <>
                    <div className="text-[9px] uppercase tracking-widest text-red-700 mt-2 mb-1.5 font-bold">Got</div>
                    <pre className="text-xs text-red-400 font-mono whitespace-pre-wrap break-all">{result.actual_output}</pre>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Bottom panel: Console + Test Cases tabs ───────────────────────────────────
function BottomPanel({ consoleLines, testCases, tcResults, running, submitting, panelHeight, onResizeStart }) {
  const [tab, setTab] = useState('console')

  // derive overall verdict color for test tab label
  const doneResults = tcResults.filter(r => r !== null)
  const allPass = doneResults.length > 0 && doneResults.every(r => r !== 'hidden' && r?.passed)
  const anyFail = doneResults.some(r => r !== null && r !== 'hidden' && !r?.passed)
  const tabColor = allPass ? 'text-emerald-400' : anyFail ? 'text-red-400' : doneResults.length > 0 ? 'text-amber-400' : 'text-gray-500'

  return (
    <div
      className="flex-shrink-0 border-t border-[#1a1a1a] bg-[#090909] flex flex-col"
      style={{ height: panelHeight }}
    >
      {/* Resize handle */}
      <div
        className="h-1 cursor-row-resize hover:bg-red-700/40 transition-colors flex-shrink-0 group"
        onMouseDown={onResizeStart}
      >
        <div className="h-px bg-[#1a1a1a] group-hover:bg-red-700/60 transition-colors" />
      </div>

      {/* Tab bar */}
      <div className="flex items-center border-b border-[#161616] px-3 h-9 gap-1 flex-shrink-0">
        {[
          { key: 'console', label: 'Console' },
          { key: 'tests',   label: 'Test Cases' },
        ].map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-3 py-1 text-xs font-mono font-semibold rounded transition-colors ${
              tab === key
                ? key === 'tests' && doneResults.length > 0
                  ? `${tabColor} bg-white/5`
                  : 'text-white bg-white/5'
                : key === 'tests' && doneResults.length > 0
                  ? `${tabColor} opacity-60 hover:opacity-100`
                  : 'text-gray-600 hover:text-gray-400'
            }`}
          >
            {label}
            {key === 'tests' && doneResults.length > 0 && (
              <span className="ml-1.5 text-[9px]">
                {doneResults.filter(r => r !== 'hidden' && r?.passed).length}/{tcResults.filter(r => r !== null).length}
              </span>
            )}
          </button>
        ))}

        <div className="flex-1" />

        {(running || submitting) && (
          <div className="flex items-center gap-1.5 text-[10px] text-gray-600 font-mono">
            <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
            {running ? 'running...' : 'judging...'}
          </div>
        )}
      </div>

      {/* Console tab */}
      {tab === 'console' && (
        <div className="flex-1 overflow-y-auto px-4 py-3 space-y-0.5">
          {consoleLines.length === 0 ? (
            <p className="text-xs text-gray-700 font-mono italic">Run your code to see output here...</p>
          ) : (
            consoleLines.map((line, i) => <ConsoleLine key={i} line={line} />)
          )}
        </div>
      )}

      {/* Test cases tab */}
      {tab === 'tests' && (
        <div className="flex-1 overflow-y-auto px-3 py-3 space-y-1.5">
          {testCases.length === 0 ? (
            <p className="text-xs text-gray-700 font-mono italic">Submit to see test results...</p>
          ) : (
            testCases.map((tc, i) => (
              <TCTile key={i} idx={i} tc={tc} result={tcResults[i] ?? null} />
            ))
          )}
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function Problem() {
  const { slug }      = useParams()
  const navigate      = useNavigate()

  const [problem,     setProblem]    = useState(null)
  const [loading,     setLoading]    = useState(true)

  // language & per-lang code
  const [language,    setLanguage]   = useState(() => getStoredLang(slug))
  const [codeByLang,  setCodeByLang] = useState(() => {
    const langs = {}
    LANGS.forEach(l => { langs[l] = getStoredCode(slug, l) })
    return langs
  })

  const [running,     setRunning]    = useState(false)
  const [submitting,  setSubmitting] = useState(false)
  const [error,       setError]      = useState('')

  // console
  const [consoleLines, setConsoleLines] = useState([])

  // test case results: array matching problem.test_cases (null = not run yet)
  const [tcResults,    setTcResults]   = useState([])
  const [allTestCases, setAllTestCases] = useState([])

  // resizable bottom panel
  const [panelHeight,  setPanelHeight] = useState(220)
  const resizeRef = useRef(null)

  // ── fetch problem ────────────────────────────────────────────────────────
  useEffect(() => {
    axios.get(`${API}/problems/${slug}`)
      .then(r => {
        setProblem(r.data)
        // Build full test case list (sample + hidden placeholders)
        // The API might return only sample_cases publicly; hidden are server-side
        const all = r.data.test_cases || r.data.sample_cases || []
        setAllTestCases(all)
        setTcResults(new Array(all.length).fill(null))
      })
      .catch(() => navigate('/problems'))
      .finally(() => setLoading(false))
  }, [slug])

  // ── code helpers ─────────────────────────────────────────────────────────
  const currentCode = codeByLang[language]

  function handleCodeChange(val) {
    const newCode = val || ''
    setCodeByLang(prev => ({ ...prev, [language]: newCode }))
    setStoredCode(slug, language, newCode)
  }

  function handleLangChange(lang) {
    setLanguage(lang)
    setStoredLang(slug, lang)
  }

  // ── resize panel ─────────────────────────────────────────────────────────
  const handleResizeStart = useCallback((e) => {
    e.preventDefault()
    const startY = e.clientY
    const startH = panelHeight
    function onMove(ev) {
      const delta = startY - ev.clientY
      setPanelHeight(Math.max(100, Math.min(500, startH + delta)))
    }
    function onUp() {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [panelHeight])

  // ── run (no judge, just run against no input or first sample) ────────────
  async function handleRun() {
    const token = localStorage.getItem('token')
    if (!token) return navigate('/login')
    setRunning(true)
    setError('')
    setConsoleLines([{ type: 'meta', text: `▶ Running (${language})...` }])

    try {
      // POST to /run — expects { stdout, stderr, time_ms, exit_code }
      const res = await axios.post(
        `${API}/run`,
      {
        problem_slug: slug,
        language,
        code: currentCode,
        stdin: problem.sample_cases?.[0]?.input || ''
  },
      const { stdout, stderr, time_ms, exit_code } = res.data
      const lines = []
      if (stdout) stdout.split('\n').forEach(l => lines.push({ type: 'stdout', text: l }))
      if (stderr) stderr.split('\n').forEach(l => lines.push({ type: 'stderr', text: l }))
      lines.push({ type: 'meta', text: `─── exited ${exit_code ?? 0} · ${time_ms ?? 0}ms ───` })
      setConsoleLines(lines)
    } catch (err) {
      const msg = err.response?.data?.error || err.message || 'run failed'
      setConsoleLines([
        { type: 'meta', text: `▶ Running (${language})...` },
        { type: 'stderr', text: msg },
      ])
      setError(msg)
    } finally {
      setRunning(false)
    }
  }

  // ── submit ───────────────────────────────────────────────────────────────
  async function handleSubmit() {
    const token = localStorage.getItem('token')
    if (!token) return navigate('/login')
    setSubmitting(true)
    setError('')
    setConsoleLines([{ type: 'meta', text: `⚡ Submitting (${language})...` }])
    // reset test results
    setTcResults(new Array(allTestCases.length).fill(null))

    try {
      const res = await axios.post(
        `${API}/submit`,
        { problem_slug: slug, language, code: currentCode },
        { headers: { Authorization: `Bearer ${token}` } }
      )
      const submissionId = res.data.id

      // poll verdict
      const poll = async () => {
        try {
          const vRes = await axios.get(`${API}/verdict/${submissionId}`)
          const v = vRes.data

          // populate test case results if returned
          if (v.test_results && Array.isArray(v.test_results)) {
            const results = v.test_results.map(r =>
              r.hidden ? 'hidden' : {
                passed: r.passed,
                time_ms: r.time_ms,
                verdict: r.verdict,
                actual_output: r.actual_output,
              }
            )
            setTcResults(results)
          }

          if (v.status === 'done') {
            const label = { AC: 'Accepted ✓', WA: 'Wrong Answer ✗', TLE: 'Time Limit Exceeded', RE: 'Runtime Error', SE: 'System Error' }
            setConsoleLines([
              { type: 'meta', text: `⚡ Submitting (${language})...` },
              { type: v.verdict === 'AC' ? 'stdout' : 'stderr', text: label[v.verdict] || v.verdict },
              { type: 'meta', text: `─── ${v.time_ms ?? 0}ms ───` },
            ])
            setSubmitting(false)
            // Navigate to verdict page after a short delay
            setTimeout(() => navigate(`/verdict/${submissionId}`), 800)
          } else {
            setTimeout(poll, 1200)
          }
        } catch {
          setSubmitting(false)
        }
      }
      poll()
    } catch (err) {
      const msg = err.response?.data?.error || 'submission failed'
      setError(msg)
      setConsoleLines([{ type: 'stderr', text: msg }])
      setSubmitting(false)
    }
  }

  // ── loading ──────────────────────────────────────────────────────────────
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
    <div className="flex h-[calc(100vh-56px)] animate-fade-in overflow-hidden">

      {/* ── LEFT: Problem statement ── */}
      <div className="w-[400px] flex-shrink-0 flex flex-col border-r border-border bg-bg overflow-hidden">

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

      {/* ── RIGHT: Editor + bottom panel ── */}
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

          {/* Action buttons */}
          <div className="flex items-center gap-2">
            {error && (
              <span className="text-xs text-red-400 font-mono max-w-[200px] truncate">{error}</span>
            )}

            {/* Run button */}
            <button
              onClick={handleRun}
              disabled={running || submitting}
              className={`flex items-center gap-1.5 px-4 py-1.5 rounded-md text-xs font-semibold border transition-all ${
                running
                  ? 'border-gray-700 text-gray-600 cursor-not-allowed'
                  : 'border-gray-700 text-gray-300 hover:border-gray-500 hover:text-white hover:bg-white/5'
              }`}
            >
              {running ? (
                <>
                  <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                  Running
                </>
              ) : (
                <>
                  <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                    <path d="M3 2l7 4-7 4V2z" fill="currentColor"/>
                  </svg>
                  Run
                </>
              )}
            </button>

            {/* Submit button */}
            <button
              onClick={handleSubmit}
              disabled={submitting || running}
              className={`flex items-center gap-1.5 px-5 py-1.5 rounded-md text-xs font-semibold transition-all ${
                submitting
                  ? 'bg-red-800/50 text-red-400 cursor-not-allowed'
                  : 'bg-red-600 hover:bg-red-500 text-white'
              }`}
            >
              {submitting ? (
                <>
                  <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                  Judging
                </>
              ) : (
                <>
                  <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                    <path d="M2 6h8M6 2l4 4-4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                  Submit
                </>
              )}
            </button>
          </div>
        </div>

        {/* Monaco — takes remaining space above bottom panel */}
        <div className="flex-1 min-h-0">
          <Editor
            height="100%"
            language={MONACO_LANG[language]}
            value={currentCode}
            onChange={handleCodeChange}
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

        {/* Bottom panel: Console + Tests */}
        <BottomPanel
          consoleLines={consoleLines}
          testCases={allTestCases}
          tcResults={tcResults}
          running={running}
          submitting={submitting}
          panelHeight={panelHeight}
          onResizeStart={handleResizeStart}
        />
      </div>
    </div>
  )
}