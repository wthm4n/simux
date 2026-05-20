import { useState, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'

const API = 'http://localhost:3000'

// ─── Tiny util ────────────────────────────────────────────────────────────────
const cls = (...a) => a.filter(Boolean).join(' ')

// ─── Design tokens (match your app) ──────────────────────────────────────────
const DIFF_STYLES = {
  easy:   'text-emerald-400 bg-emerald-950/50 border-emerald-800',
  medium: 'text-amber-400   bg-amber-950/50   border-amber-800',
  hard:   'text-red-400     bg-red-950/50     border-red-800',
}

const DIFF_DOT = { easy: 'bg-emerald-500', medium: 'bg-amber-500', hard: 'bg-red-500' }

const TOPIC_OPTIONS = [
  'Arrays','Strings','Hash Map','Two Pointers','Sliding Window',
  'Binary Search','Sorting','Stack','Queue','Linked List',
  'Trees','Graphs','DFS','BFS','Dynamic Programming',
  'Greedy','Math','Bit Manipulation','Recursion','Backtracking',
]

// ─── Sub-components ───────────────────────────────────────────────────────────

function StepBar({ current }) {
  const steps = ['Details', 'Statement', 'Test Cases', 'Review']
  return (
    <div className="flex items-center mb-10">
      {steps.map((label, i) => {
        const idx = i + 1
        const done   = idx < current
        const active = idx === current
        return (
          <div key={label} className="flex items-center flex-1 last:flex-none">
            <div className="flex flex-col items-center gap-1.5">
              <div className={cls(
                'w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold font-mono border transition-all duration-300',
                done   ? 'bg-red-600 border-red-600 text-white' :
                active ? 'bg-transparent border-red-500 text-red-400 shadow-[0_0_14px_rgba(239,68,68,0.35)]' :
                         'bg-transparent border-gray-800 text-gray-700'
              )}>
                {done ? (
                  <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
                    <path d="M2 6l3 3 5-5" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                ) : idx}
              </div>
              <span className={cls(
                'text-[10px] font-bold uppercase tracking-widest whitespace-nowrap',
                active ? 'text-red-400' : done ? 'text-gray-500' : 'text-gray-700'
              )}>{label}</span>
            </div>
            {i < steps.length - 1 && (
              <div className={cls(
                'flex-1 h-px mx-3 mb-5 transition-all duration-500',
                done ? 'bg-gradient-to-r from-red-700 to-red-900' : 'bg-gray-800'
              )} />
            )}
          </div>
        )
      })}
    </div>
  )
}

function Field({ label, hint, error, children }) {
  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <label className="text-[11px] font-bold uppercase tracking-widest text-gray-500">{label}</label>
        {hint && <span className="text-[10px] text-gray-700 font-mono">{hint}</span>}
      </div>
      {children}
      {error && <p className="text-xs text-red-500 mt-1 font-mono">{error}</p>}
    </div>
  )
}

function Input({ className = '', error, ...props }) {
  return (
    <input
      {...props}
      className={cls(
        'w-full bg-[#0a0a0a] border rounded-lg px-4 py-2.5 text-sm text-gray-200',
        'placeholder-gray-700 font-mono focus:outline-none transition-all',
        error
          ? 'border-red-800 focus:border-red-500 focus:shadow-[0_0_0_3px_rgba(220,38,38,0.15)]'
          : 'border-[#1f1f1f] focus:border-red-600 focus:shadow-[0_0_0_3px_rgba(220,38,38,0.12)]',
        className
      )}
    />
  )
}

function Textarea({ className = '', rows = 4, ...props }) {
  return (
    <textarea
      rows={rows}
      {...props}
      className={cls(
        'w-full bg-[#0a0a0a] border border-[#1f1f1f] rounded-lg px-4 py-3 text-sm text-gray-200',
        'placeholder-gray-700 font-mono focus:outline-none focus:border-red-600',
        'focus:shadow-[0_0_0_3px_rgba(220,38,38,0.12)] transition-all resize-none',
        className
      )}
    />
  )
}

function Card({ children, className = '' }) {
  return (
    <div className={cls('bg-[#0e0e0e] border border-[#1a1a1a] rounded-2xl p-6', className)}>
      {children}
    </div>
  )
}

function SectionTitle({ children }) {
  return (
    <h2 className="text-[11px] font-bold text-gray-500 uppercase tracking-widest mb-5 flex items-center gap-2">
      <span className="w-3 h-px bg-red-700" />
      {children}
    </h2>
  )
}

// ─── Markdown renderer (richer than before) ───────────────────────────────────
function MarkdownPreview({ text, images = [] }) {
  if (!text?.trim()) return (
    <p className="text-gray-700 italic text-sm py-4 text-center">Nothing to preview yet...</p>
  )

  // Build image map for inline rendering
  const imgMap = {}
  images.forEach(img => { imgMap[img.name] = img.dataUrl })

  // Split on image tags first, then process text
  const parts = text.split(/(!\[[^\]]*\])/g)

  return (
    <div className="prose prose-invert prose-sm max-w-none">
      {parts.map((part, i) => {
        const imgMatch = part.match(/^!\[([^\]]*)\]$/)
        if (imgMatch) {
          const name = imgMatch[1]
          const src  = imgMap[name]
          return src ? (
            <img key={i} src={src} alt={name}
              className="rounded-lg border border-[#222] max-w-full my-3 mx-auto block"
              style={{ maxHeight: 320 }}
            />
          ) : (
            <span key={i} className="text-xs text-red-500 font-mono bg-red-950/30 px-2 py-0.5 rounded">
              [image: {name} not found]
            </span>
          )
        }

        // Process text chunk
        const html = part
          .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
          .replace(/^### (.+)$/gm, '<h3 class="text-sm font-bold text-gray-200 mt-4 mb-1">$1</h3>')
          .replace(/^## (.+)$/gm,  '<h2 class="text-base font-bold text-gray-100 mt-5 mb-2">$1</h2>')
          .replace(/^# (.+)$/gm,   '<h1 class="text-lg font-bold text-white mt-6 mb-2">$1</h1>')
          .replace(/\*\*(.+?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
          .replace(/\*(.+?)\*/g,     '<em class="text-gray-300">$1</em>')
          .replace(/`([^`]+)`/g,
            '<code class="bg-[#1c1c1c] border border-[#2a2a2a] px-1.5 py-0.5 rounded text-red-400 font-mono text-xs">$1</code>')
          .replace(/^&gt; (.+)$/gm,
            '<blockquote class="border-l-2 border-red-700 pl-3 text-gray-400 italic my-2">$1</blockquote>')
          .replace(/\n/g, '<br/>')

        return <span key={i} className="text-sm text-gray-300 leading-relaxed"
          dangerouslySetInnerHTML={{ __html: html }} />
      })}
    </div>
  )
}

// ─── Test case row with drag handle ──────────────────────────────────────────
function TestCaseRow({ tc, idx, onChange, onRemove, canRemove, dragHandleProps, isDragging }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div className={cls(
      'rounded-xl border transition-all duration-200',
      isDragging ? 'scale-[1.01] shadow-2xl shadow-black/50 opacity-90' : '',
      tc.is_sample
        ? 'border-red-800/50 bg-red-950/8'
        : 'border-[#1a1a1a] bg-[#0b0b0b]'
    )}>
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[#161616]">
        {/* Drag handle */}
        <div
          {...dragHandleProps}
          className="cursor-grab active:cursor-grabbing text-gray-700 hover:text-gray-500 transition-colors flex-shrink-0 p-1"
        >
          <svg width="10" height="14" viewBox="0 0 10 14" fill="none">
            <circle cx="3" cy="2.5" r="1.2" fill="currentColor"/>
            <circle cx="7" cy="2.5" r="1.2" fill="currentColor"/>
            <circle cx="3" cy="7" r="1.2" fill="currentColor"/>
            <circle cx="7" cy="7" r="1.2" fill="currentColor"/>
            <circle cx="3" cy="11.5" r="1.2" fill="currentColor"/>
            <circle cx="7" cy="11.5" r="1.2" fill="currentColor"/>
          </svg>
        </div>

        <span className="text-[11px] font-bold uppercase tracking-widest text-gray-600 font-mono flex-shrink-0">
          #{String(idx + 1).padStart(2,'0')}
        </span>

        {tc.is_sample && (
          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded-sm bg-red-900/40 text-red-400 border border-red-800/50 tracking-widest uppercase">
            PUBLIC
          </span>
        )}

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => onChange({ ...tc, is_sample: !tc.is_sample })}
            className={cls(
              'flex items-center gap-1.5 text-[11px] font-semibold px-2.5 py-1 rounded-md transition-all',
              tc.is_sample
                ? 'bg-red-900/30 text-red-400 border border-red-800/50'
                : 'bg-[#141414] text-gray-600 border border-[#1f1f1f] hover:text-gray-400 hover:border-[#2a2a2a]'
            )}
          >
            <span className={cls('w-1.5 h-1.5 rounded-full', tc.is_sample ? 'bg-red-500' : 'bg-gray-700')} />
            {tc.is_sample ? 'Public' : 'Hidden'}
          </button>

          <button
            onClick={() => setCollapsed(c => !c)}
            className="w-6 h-6 rounded flex items-center justify-center text-gray-700 hover:text-gray-400 transition-colors"
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none"
              style={{ transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)', transition:'transform 0.2s' }}>
              <path d="M2 4l3 3 3-3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>

          {canRemove && (
            <button
              onClick={onRemove}
              className="w-6 h-6 rounded flex items-center justify-center text-gray-700 hover:text-red-400 hover:bg-red-950/20 transition-all"
            >
              <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                <path d="M1.5 1.5l7 7M8.5 1.5l-7 7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Body */}
      {!collapsed && (
        <div className="grid grid-cols-2 divide-x divide-[#161616]">
          <div className="p-3 space-y-1.5">
            <div className="text-[9px] uppercase tracking-widest text-gray-700 font-bold">Input</div>
            <Textarea
              rows={3}
              value={tc.input}
              onChange={e => onChange({ ...tc, input: e.target.value })}
              placeholder="stdin..."
              className="text-xs"
            />
          </div>
          <div className="p-3 space-y-1.5">
            <div className="text-[9px] uppercase tracking-widest text-gray-700 font-bold">Expected Output</div>
            <Textarea
              rows={3}
              value={tc.expected_output}
              onChange={e => onChange({ ...tc, expected_output: e.target.value })}
              placeholder="stdout..."
              className="text-xs"
            />
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Bulk Import Modal ────────────────────────────────────────────────────────
function BulkImportModal({ onClose, onImport }) {
  const [raw, setRaw] = useState('')
  const [separator, setSeparator] = useState('---')
  const [asPublic, setAsPublic] = useState(false)

  function parse() {
    const blocks = raw.split(/\n?---+\n?/).map(b => b.trim()).filter(Boolean)
    const pairs = []
    for (let i = 0; i + 1 < blocks.length; i += 2) {
      pairs.push({ input: blocks[i], expected_output: blocks[i+1], is_sample: asPublic })
    }
    return pairs
  }

  const preview = parse()

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="w-full max-w-2xl bg-[#0e0e0e] border border-[#222] rounded-2xl p-6 mx-4 shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <h3 className="text-sm font-bold text-white uppercase tracking-widest">Bulk Import Test Cases</h3>
          <button onClick={onClose} className="text-gray-600 hover:text-gray-300 transition-colors">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
        </div>

        <p className="text-xs text-gray-600 mb-4 font-mono">
          Paste test cases separated by <code className="text-red-400">---</code>. Format: input block → <code className="text-red-400">---</code> → output block → <code className="text-red-400">---</code> → next input...
        </p>

        <Textarea
          rows={12}
          value={raw}
          onChange={e => setRaw(e.target.value)}
          placeholder={`5\n---\n10\n---\n0\n---\n0\n---\n100\n---\n200`}
          className="text-xs mb-4"
        />

        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-500 font-mono">
              {preview.length} test case{preview.length !== 1 ? 's' : ''} detected
            </span>
          </div>
          <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-500">
            <div
              onClick={() => setAsPublic(v => !v)}
              className={cls(
                'w-8 h-4 rounded-full transition-all relative cursor-pointer',
                asPublic ? 'bg-red-600' : 'bg-gray-800'
              )}
            >
              <span className={cls(
                'absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all',
                asPublic ? 'left-4' : 'left-0.5'
              )} />
            </div>
            Mark all as Public
          </label>
        </div>

        <div className="flex gap-3">
          <button onClick={onClose}
            className="flex-1 py-2.5 rounded-lg border border-[#222] text-gray-500 hover:text-gray-300 text-sm font-medium transition-colors">
            Cancel
          </button>
          <button
            onClick={() => { onImport(preview); onClose() }}
            disabled={preview.length === 0}
            className="flex-1 py-2.5 rounded-lg bg-red-600 hover:bg-red-500 disabled:opacity-30 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors"
          >
            Import {preview.length > 0 ? `${preview.length} Cases` : ''}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── AI Test Case Generator ───────────────────────────────────────────────────
function AIGeneratorModal({ details, desc, onClose, onImport }) {
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [count, setCount] = useState(18)

  async function generate() {
    if (!details.title || !desc.description) return
    setLoading(true)
    setError('')
    setResult(null)

    const token = localStorage.getItem('token')

    try {
      // API key stays server-side — call our own backend proxy
      const res = await fetch(`${API}/ai/generate-testcases`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({
          title:         details.title,
          difficulty:    details.difficulty,
          time_limit:    details.time_limit,
          description:   desc.description,
          input_format:  desc.input_format,
          output_format: desc.output_format,
          constraints:   desc.constraints,
          count,
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error || 'server error')
      const parsed = data.test_cases
      if (!Array.isArray(parsed)) throw new Error('Unexpected response format')
      setResult(parsed)
    } catch (e) {
      setError(e.message || 'Failed to generate test cases. Try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
      <div className="w-full max-w-2xl bg-[#0e0e0e] border border-[#222] rounded-2xl p-6 mx-4 shadow-2xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold uppercase tracking-widest text-red-500 border border-red-900 px-2 py-0.5 rounded font-mono">AI</span>
            <h3 className="text-sm font-bold text-white uppercase tracking-widest">Generate Test Cases</h3>
          </div>
          <button onClick={onClose} className="text-gray-600 hover:text-gray-300 transition-colors">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M1 1l12 12M13 1L1 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
        </div>

        {!result ? (
          <>
            <p className="text-xs text-gray-500 mb-5">
              AI will analyze your problem statement and generate test cases with edge cases and stress tests.
              <span className="text-yellow-600"> Make sure you verify all generated cases before publishing.</span>
            </p>

            <div className="space-y-4 mb-6">
              <Field label="Number of cases to generate">
                <div className="flex gap-2">
                  {[10, 15, 18, 20, 25].map(n => (
                    <button key={n} onClick={() => setCount(n)}
                      className={cls(
                        'flex-1 py-2 rounded-lg text-xs font-bold font-mono border transition-all',
                        count === n
                          ? 'bg-red-600 border-red-600 text-white'
                          : 'border-[#222] text-gray-600 hover:text-gray-400 hover:border-[#333]'
                      )}
                    >{n}</button>
                  ))}
                </div>
              </Field>
            </div>

            {error && (
              <div className="mb-4 text-xs text-red-400 bg-red-950/30 border border-red-900 rounded-lg px-4 py-3 font-mono">
                {error}
              </div>
            )}

            <div className="flex gap-3">
              <button onClick={onClose}
                className="flex-1 py-2.5 rounded-lg border border-[#222] text-gray-500 hover:text-gray-300 text-sm font-medium transition-colors">
                Cancel
              </button>
              <button
                onClick={generate}
                disabled={loading || !details.title || !desc.description}
                className="flex-1 py-2.5 rounded-lg bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold transition-all flex items-center justify-center gap-2"
              >
                {loading ? (
                  <>
                    <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                    </svg>
                    Generating...
                  </>
                ) : `Generate ${count} Cases`}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="mb-4 flex items-center gap-2 text-sm text-emerald-400 bg-emerald-950/20 border border-emerald-900/40 rounded-lg px-4 py-3">
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                <circle cx="7" cy="7" r="6" stroke="#34d399" strokeWidth="1.5"/>
                <path d="M4 7l2 2 4-4" stroke="#34d399" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
              Generated {result.length} test cases — review before importing
            </div>

            <div className="space-y-2 mb-5 max-h-60 overflow-y-auto">
              {result.map((tc, i) => (
                <div key={i} className="bg-[#0c0c0c] border border-[#1a1a1a] rounded-lg p-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <div className="text-[9px] uppercase tracking-widest text-gray-700 mb-1 font-bold">Input</div>
                      <pre className="text-xs text-gray-400 font-mono whitespace-pre-wrap">{tc.input}</pre>
                    </div>
                    <div>
                      <div className="text-[9px] uppercase tracking-widest text-gray-700 mb-1 font-bold">Output</div>
                      <pre className="text-xs text-gray-400 font-mono whitespace-pre-wrap">{tc.expected_output}</pre>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            <p className="text-[10px] text-gray-700 mb-4 font-mono">
              ⚠ Always manually verify AI-generated cases. The AI may misinterpret edge cases.
            </p>

            <div className="flex gap-3">
              <button onClick={() => setResult(null)}
                className="flex-1 py-2.5 rounded-lg border border-[#222] text-gray-500 hover:text-gray-300 text-sm font-medium transition-colors">
                Re-generate
              </button>
              <button
                onClick={() => { onImport(result.map(tc => ({ ...tc, is_sample: false }))); onClose() }}
                className="flex-1 py-2.5 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm font-semibold transition-colors"
              >
                Import All as Hidden
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ─── Live Problem Preview (mimics Problem.jsx layout) ────────────────────────
function ProblemPreview({ details, desc, testCases }) {
  const sampleCases = testCases.filter(tc => tc.is_sample && tc.input && tc.expected_output)

  const fullDesc = [
    desc.description,
    desc.input_format  ? `**Input Format**\n${desc.input_format}`   : '',
    desc.output_format ? `**Output Format**\n${desc.output_format}` : '',
    desc.constraints   ? `**Constraints**\n${desc.constraints}`     : '',
  ].filter(Boolean).join('\n\n')

  return (
    <div className="bg-[#0b0b0b] border border-[#1a1a1a] rounded-2xl overflow-hidden">
      {/* Mimics Problem.jsx left panel header */}
      <div className="px-6 pt-6 pb-4 border-b border-[#1a1a1a]">
        <div className="flex items-start justify-between gap-3 mb-3">
          <h1 className="text-lg font-bold tracking-tight leading-snug text-white">
            {details.title || <span className="text-gray-700 italic">Problem title...</span>}
          </h1>
          <span className={cls('text-xs font-semibold flex-shrink-0 mt-0.5', DIFF_STYLES[details.difficulty]?.split(' ')[0])}>
            {details.difficulty}
          </span>
        </div>
        <div className="flex gap-4 text-xs text-gray-600 font-mono">
          <span>⏱ {details.time_limit}ms</span>
          <span>💾 {details.mem_limit}MB</span>
          {details.tags?.length > 0 && (
            <span className="text-gray-700">
              {details.tags.join(' · ')}
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div className="px-6 py-5 space-y-6">
        <div>
          <MarkdownPreview text={fullDesc} images={desc.images} />
        </div>

        {sampleCases.length > 0 && (
          <div>
            <h2 className="text-[11px] font-semibold uppercase tracking-widest text-gray-600 mb-3">
              Sample Cases
            </h2>
            <div className="space-y-3">
              {sampleCases.map((tc, i) => (
                <div key={i} className="rounded-lg border border-[#1a1a1a] overflow-hidden">
                  <div className="grid grid-cols-2 divide-x divide-[#1a1a1a]">
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
  )
}

// ─── MAIN COMPONENT ───────────────────────────────────────────────────────────
export default function AdminPanel() {
  const navigate  = useNavigate()
  const token     = localStorage.getItem('token')
  const role      = localStorage.getItem('role')

  const [step,       setStep]       = useState(1)
  const [submitting, setSubmitting] = useState(false)
  const [done,       setDone]       = useState(null)
  const [errors,     setErrors]     = useState({})

  // Modals
  const [showBulk,   setShowBulk]   = useState(false)
  const [showAI,     setShowAI]     = useState(false)

  // ── Step 1: Details ──────────────────────────────────────────────────────
  const [details, setDetails] = useState({
    title:      '',
    slug:       '',
    difficulty: 'medium',
    time_limit: 2000,
    mem_limit:  256,
    tags:       [],
  })

  // ── Step 2: Description ──────────────────────────────────────────────────
  const [desc, setDesc] = useState({
    description:   '',
    input_format:  '',
    output_format: '',
    constraints:   '',
    notes:         '',
    images:        [], // { name, dataUrl }
  })
  const [descTab, setDescTab] = useState('write')
  const [descSection, setDescSection] = useState('description')
  const imgRef = useRef()

  // ── Step 3: Test cases ───────────────────────────────────────────────────
  const emptyTC = (sample = false) => ({ input: '', expected_output: '', is_sample: sample })
  const [testCases, setTestCases] = useState([
    emptyTC(true),
    emptyTC(true),
    ...Array.from({ length: 18 }, () => emptyTC(false)),
  ])

  // Drag state
  const [dragIdx, setDragIdx] = useState(null)
  const [dragOver, setDragOver] = useState(null)

  // ── Helpers ──────────────────────────────────────────────────────────────
  function handleTitleChange(val) {
    const slug = val.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
    setDetails(d => ({ ...d, title: val, slug }))
  }

  function toggleTag(tag) {
    setDetails(d => ({
      ...d,
      tags: d.tags.includes(tag) ? d.tags.filter(t => t !== tag) : [...d.tags, tag],
    }))
  }

  function handleImageUpload(e) {
    const files = Array.from(e.target.files)
    files.forEach(file => {
      const reader = new FileReader()
      reader.onload = ev => {
        setDesc(d => ({ ...d, images: [...d.images, { name: file.name, dataUrl: ev.target.result }] }))
      }
      reader.readAsDataURL(file)
    })
    e.target.value = ''
  }

  function insertImageTag(name) {
    setDesc(d => ({ ...d, description: d.description + `\n![${name}]` }))
    setDescSection('description')
    setDescTab('write')
  }

  function removeImage(i) {
    setDesc(d => ({ ...d, images: d.images.filter((_, idx) => idx !== i) }))
  }

  // Test case helpers
  function updateTC(i, val) { setTestCases(tcs => tcs.map((t, idx) => idx === i ? val : t)) }
  function removeTC(i) { setTestCases(tcs => tcs.filter((_, idx) => idx !== i)) }
  function addTC(sample = false) { setTestCases(tcs => [...tcs, emptyTC(sample)]) }

  function importTCs(newCases) {
    setTestCases(tcs => [...tcs, ...newCases])
  }

  function clearAllHidden() {
    if (!window.confirm('Remove all hidden test cases?')) return
    setTestCases(tcs => tcs.filter(t => t.is_sample))
  }

  // Drag-to-reorder
  function handleDragStart(i) { setDragIdx(i) }
  function handleDragEnter(i) { setDragOver(i) }
  function handleDragEnd() {
    if (dragIdx !== null && dragOver !== null && dragIdx !== dragOver) {
      const arr = [...testCases]
      const [moved] = arr.splice(dragIdx, 1)
      arr.splice(dragOver, 0, moved)
      setTestCases(arr)
    }
    setDragIdx(null)
    setDragOver(null)
  }

  const publicCount = testCases.filter(t => t.is_sample).length
  const hiddenCount = testCases.filter(t => !t.is_sample).length

  // ── Validation ───────────────────────────────────────────────────────────
  function validateStep(s) {
    const errs = {}
    if (s === 1) {
      if (!details.title.trim())       errs.title      = 'Required'
      if (!details.slug.trim())        errs.slug       = 'Required'
      if (details.time_limit < 100)    errs.time_limit = 'Min 100ms'
      if (details.time_limit > 10000)  errs.time_limit = 'Max 10000ms'
      if (details.mem_limit < 16)      errs.mem_limit  = 'Min 16MB'
    }
    if (s === 2) {
      if (!desc.description.trim()) errs.description = 'Problem statement is required'
    }
    if (s === 3) {
      if (testCases.length < 1) errs.testCases = 'Add at least 1 test case'
      if (publicCount < 1) errs.testCases = 'Add at least 1 public (sample) test case'
      testCases.forEach((tc, i) => {
        if (!tc.input.trim() || !tc.expected_output.trim())
          errs[`tc_${i}`] = 'Fill both input and output'
      })
    }
    setErrors(errs)
    return Object.keys(errs).length === 0
  }

  function nextStep() {
    if (validateStep(step)) setStep(s => s + 1)
  }

  // ── Submit ───────────────────────────────────────────────────────────────
  async function handleSubmit() {
    if (!validateStep(3)) return
    setSubmitting(true)

    let fullDesc = desc.description.trim()
    if (desc.input_format.trim())  fullDesc += `\n\n**Input Format**\n${desc.input_format.trim()}`
    if (desc.output_format.trim()) fullDesc += `\n\n**Output Format**\n${desc.output_format.trim()}`
    if (desc.constraints.trim())   fullDesc += `\n\n**Constraints**\n${desc.constraints.trim()}`
    if (desc.notes.trim())         fullDesc += `\n\n**Notes**\n${desc.notes.trim()}`

    const payload = {
      slug:        details.slug,
      title:       details.title,
      description: fullDesc,
      difficulty:  details.difficulty,
      time_limit:  Number(details.time_limit),
      mem_limit:   Number(details.mem_limit),
      test_cases:  testCases.map(tc => ({
        input:           tc.input,
        expected_output: tc.expected_output,
        is_sample:       tc.is_sample,
      })),
    }

    try {
      const res = await axios.post(`${API}/problems`, payload, {
        headers: { Authorization: `Bearer ${token}` },
      })
      setDone(res.data)
    } catch (err) {
      setErrors({ submit: err.response?.data?.error || 'Submit failed' })
      setSubmitting(false)
    }
  }

  function resetAll() {
    setDone(null); setStep(1); setErrors({})
    setDetails({ title:'', slug:'', difficulty:'medium', time_limit:2000, mem_limit:256, tags:[] })
    setDesc({ description:'', input_format:'', output_format:'', constraints:'', notes:'', images:[] })
    setTestCases([emptyTC(true), emptyTC(true), ...Array.from({length:18}, () => emptyTC(false))])
  }

  // ── Guard ────────────────────────────────────────────────────────────────
  if (!token || role !== 'admin') {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-56px)]">
        <div className="text-center space-y-3">
          <div className="w-12 h-12 rounded-full border border-red-900 flex items-center justify-center mx-auto">
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
              <rect x="3" y="8" width="12" height="9" rx="2" stroke="#dc2626" strokeWidth="1.5"/>
              <path d="M6 8V6a3 3 0 016 0v2" stroke="#dc2626" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </div>
          <p className="text-gray-500 text-sm">Admin access required</p>
          <button onClick={() => navigate('/login')}
            className="text-xs text-red-500 hover:text-red-400 transition-colors font-mono">
            → Sign in as admin
          </button>
        </div>
      </div>
    )
  }

  // ── Success screen ───────────────────────────────────────────────────────
  if (done) {
    return (
      <div className="flex items-center justify-center min-h-[calc(100vh-56px)] px-4">
        <div className="w-full max-w-sm text-center space-y-6 animate-slide-up">
          <div className="relative mx-auto w-16 h-16">
            <div className="w-16 h-16 rounded-full border-2 border-emerald-500/30 absolute animate-ping" />
            <div className="w-16 h-16 rounded-full border-2 border-emerald-500 flex items-center justify-center relative">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                <path d="M5 12l4 4 10-10" stroke="#34d399" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
          </div>
          <div>
            <h2 className="text-2xl font-bold text-white mb-2">Problem Published</h2>
            <p className="text-gray-500 text-sm font-mono">/{done.slug}</p>
            <p className="text-gray-700 text-xs mt-1">ID: {done.id}</p>
          </div>
          <div className="flex gap-3">
            <button onClick={resetAll}
              className="flex-1 bg-[#141414] border border-[#1f1f1f] text-gray-300 hover:text-white py-2.5 rounded-lg text-sm font-medium transition-colors">
              + New Problem
            </button>
            <button onClick={() => navigate(`/problems/${done.slug}`)}
              className="flex-1 bg-red-600 hover:bg-red-500 text-white py-2.5 rounded-lg text-sm font-semibold transition-colors">
              View Problem →
            </button>
          </div>
        </div>
      </div>
    )
  }

  // ─────────────────────────────────────────────────────────────────────────
  return (
    <>
      {showBulk && <BulkImportModal onClose={() => setShowBulk(false)} onImport={importTCs} />}
      {showAI   && <AIGeneratorModal details={details} desc={desc} onClose={() => setShowAI(false)} onImport={importTCs} />}

      <div className="max-w-5xl mx-auto px-6 py-10 animate-fade-in">

        {/* Header */}
        <div className="mb-8 flex items-end justify-between">
          <div>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[9px] font-bold uppercase tracking-widest text-red-500 border border-red-900/60 px-2 py-0.5 rounded font-mono">
                admin
              </span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight">New Problem</h1>
            <p className="text-gray-600 text-sm mt-1">Create a problem with full statement, examples, and test cases</p>
          </div>
          <button
            onClick={() => navigate('/problems')}
            className="flex items-center gap-2 text-xs text-gray-600 hover:text-gray-400 transition-colors font-mono"
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path d="M8 2L3 6l5 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            Back to problems
          </button>
        </div>

        <StepBar current={step} />

        {/* ── STEP 1: Details ───────────────────────────────────────────── */}
        {step === 1 && (
          <div className="space-y-5 animate-fade-in">
            <Card>
              <SectionTitle>Basic Info</SectionTitle>
              <div className="space-y-5">

                <Field label="Problem Title" hint="concise & clear" error={errors.title}>
                  <Input
                    autoFocus
                    value={details.title}
                    onChange={e => handleTitleChange(e.target.value)}
                    placeholder="e.g. Two Sum, Maximum Subarray..."
                    error={errors.title}
                  />
                </Field>

                <Field label="URL Slug" hint="auto-generated · editable" error={errors.slug}>
                  <div className="relative">
                    <span className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-600 text-sm font-mono select-none">/</span>
                    <Input
                      value={details.slug}
                      onChange={e => setDetails(d => ({ ...d, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '') }))}
                      placeholder="two-sum"
                      className="pl-7"
                      error={errors.slug}
                    />
                  </div>
                </Field>

                <Field label="Difficulty">
                  <div className="flex gap-2">
                    {['easy','medium','hard'].map(d => (
                      <button
                        key={d}
                        onClick={() => setDetails(det => ({ ...det, difficulty: d }))}
                        className={cls(
                          'flex-1 py-2.5 rounded-lg text-sm font-semibold capitalize border transition-all flex items-center justify-center gap-2',
                          details.difficulty === d
                            ? DIFF_STYLES[d]
                            : 'border-[#1f1f1f] text-gray-700 hover:text-gray-400 hover:border-[#2a2a2a]'
                        )}
                      >
                        <span className={cls('w-1.5 h-1.5 rounded-full', details.difficulty === d ? DIFF_DOT[d] : 'bg-gray-700')} />
                        {d}
                      </button>
                    ))}
                  </div>
                </Field>

                <div className="grid grid-cols-2 gap-4">
                  <Field label="Time Limit" hint="ms (100–10000)" error={errors.time_limit}>
                    <Input
                      type="number"
                      value={details.time_limit}
                      onChange={e => setDetails(d => ({ ...d, time_limit: e.target.value }))}
                      min={100} max={10000}
                      error={errors.time_limit}
                    />
                  </Field>
                  <Field label="Memory Limit" hint="MB (16–1024)" error={errors.mem_limit}>
                    <Input
                      type="number"
                      value={details.mem_limit}
                      onChange={e => setDetails(d => ({ ...d, mem_limit: e.target.value }))}
                      min={16} max={1024}
                      error={errors.mem_limit}
                    />
                  </Field>
                </div>
              </div>
            </Card>

            {/* Tags */}
            <Card>
              <SectionTitle>Topics & Tags <span className="text-gray-700 font-normal normal-case tracking-normal ml-1">optional</span></SectionTitle>
              <div className="flex flex-wrap gap-2">
                {TOPIC_OPTIONS.map(tag => (
                  <button
                    key={tag}
                    onClick={() => toggleTag(tag)}
                    className={cls(
                      'px-3 py-1.5 rounded-lg text-xs font-medium border transition-all',
                      details.tags.includes(tag)
                        ? 'bg-red-900/30 border-red-700/60 text-red-400'
                        : 'bg-transparent border-[#1f1f1f] text-gray-600 hover:text-gray-400 hover:border-[#2a2a2a]'
                    )}
                  >
                    {tag}
                  </button>
                ))}
              </div>
              {details.tags.length > 0 && (
                <p className="text-[10px] text-gray-700 mt-3 font-mono">
                  Selected: {details.tags.join(', ')}
                </p>
              )}
            </Card>
          </div>
        )}

        {/* ── STEP 2: Problem Statement ─────────────────────────────────── */}
        {step === 2 && (
          <div className="space-y-5 animate-fade-in">
            <Card>
              {/* Tabs: section + write/preview */}
              <div className="flex items-center justify-between mb-5">
                <div className="flex gap-1 bg-[#0a0a0a] border border-[#1a1a1a] rounded-lg p-1">
                  {[
                    ['description', 'Statement'],
                    ['input_format', 'Input'],
                    ['output_format', 'Output'],
                    ['constraints', 'Constraints'],
                    ['notes', 'Notes'],
                  ].map(([key, label]) => (
                    <button
                      key={key}
                      onClick={() => setDescSection(key)}
                      className={cls(
                        'px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider rounded-md transition-all',
                        descSection === key
                          ? 'bg-red-600 text-white'
                          : 'text-gray-600 hover:text-gray-400'
                      )}
                    >
                      {label}
                      {key === 'description' && !desc.description && (
                        <span className="ml-1 w-1 h-1 rounded-full bg-red-500 inline-block" />
                      )}
                    </button>
                  ))}
                </div>

                <div className="flex rounded-lg overflow-hidden border border-[#1a1a1a]">
                  {['write','preview'].map(t => (
                    <button
                      key={t}
                      onClick={() => setDescTab(t)}
                      className={cls(
                        'px-4 py-1.5 text-[11px] font-bold uppercase tracking-wider transition-all',
                        descTab === t ? 'bg-red-600 text-white' : 'text-gray-600 hover:text-gray-400'
                      )}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              {/* Hint for active section */}
              <div className="mb-3">
                {descSection === 'description' && (
                  <p className="text-[10px] text-gray-700 font-mono">
                    Full problem statement. Supports **bold**, *italic*, `code`, # headers, &gt; quotes.
                    {desc.images.length > 0 && ' Use ![filename] to embed uploaded images.'}
                  </p>
                )}
                {descSection === 'input_format' && (
                  <p className="text-[10px] text-gray-700 font-mono">Describe the input format line by line.</p>
                )}
                {descSection === 'output_format' && (
                  <p className="text-[10px] text-gray-700 font-mono">Describe what the output should look like.</p>
                )}
                {descSection === 'constraints' && (
                  <p className="text-[10px] text-gray-700 font-mono">List constraints like: 1 ≤ N ≤ 10^5</p>
                )}
                {descSection === 'notes' && (
                  <p className="text-[10px] text-gray-700 font-mono">Extra notes, explanations, or example walkthroughs.</p>
                )}
              </div>

              {descTab === 'write' ? (
                <Textarea
                  key={descSection}
                  autoFocus
                  rows={descSection === 'description' ? 12 : 6}
                  value={desc[descSection]}
                  onChange={e => setDesc(d => ({ ...d, [descSection]: e.target.value }))}
                  placeholder={
                    descSection === 'description' ? 'Write the problem statement here...\n\nSupports **bold**, *italic*, `code`, # Heading, > blockquote' :
                    descSection === 'input_format' ? 'First line contains integer N...' :
                    descSection === 'output_format' ? 'Print a single integer on one line...' :
                    descSection === 'constraints' ? '1 ≤ N ≤ 10^5\n1 ≤ A[i] ≤ 10^9' :
                    'Optional extra notes or example walkthroughs...'
                  }
                />
              ) : (
                <div className="min-h-[200px] bg-[#080808] border border-[#1a1a1a] rounded-lg px-5 py-4">
                  <MarkdownPreview text={desc[descSection]} images={desc.images} />
                </div>
              )}

              {descSection === 'description' && errors.description && (
                <p className="text-xs text-red-500 mt-2 font-mono">{errors.description}</p>
              )}
            </Card>

            {/* Images */}
            <Card>
              <SectionTitle>Images <span className="text-gray-700 font-normal normal-case tracking-normal ml-1">optional</span></SectionTitle>
              <p className="text-[10px] text-gray-700 mb-4 font-mono">
                Upload images and reference them in the statement with{' '}
                <code className="bg-[#1a1a1a] px-1.5 py-0.5 rounded text-red-400">![filename]</code>
              </p>

              <input
                ref={imgRef}
                type="file"
                accept="image/*"
                multiple
                className="hidden"
                onChange={handleImageUpload}
              />

              {desc.images.length === 0 ? (
                <button
                  onClick={() => imgRef.current.click()}
                  className="w-full flex flex-col items-center justify-center gap-2 py-8 border border-dashed border-[#1f1f1f] rounded-xl text-gray-700 hover:text-gray-500 hover:border-[#2a2a2a] transition-all"
                >
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                    <path d="M10 4v12M4 10h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                  <span className="text-xs font-medium">Click to upload images</span>
                  <span className="text-[10px] font-mono">PNG, JPG, GIF, WebP</span>
                </button>
              ) : (
                <div className="space-y-3">
                  <div className="grid grid-cols-4 gap-3">
                    {desc.images.map((img, i) => (
                      <div key={i} className="relative group rounded-lg overflow-hidden border border-[#1f1f1f] bg-[#0a0a0a]">
                        <img src={img.dataUrl} alt={img.name} className="w-full h-20 object-cover" />
                        <div className="absolute inset-0 bg-black/75 opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-center justify-center gap-1.5 p-2">
                          <p className="text-[9px] text-white font-mono truncate w-full text-center">{img.name}</p>
                          <div className="flex gap-1">
                            <button
                              onClick={() => insertImageTag(img.name)}
                              className="text-[9px] bg-red-600 text-white px-2 py-1 rounded font-bold"
                            >Insert</button>
                            <button
                              onClick={() => removeImage(i)}
                              className="text-[9px] bg-[#2a2a2a] text-gray-400 px-2 py-1 rounded"
                            >✕</button>
                          </div>
                        </div>
                      </div>
                    ))}
                    <button
                      onClick={() => imgRef.current.click()}
                      className="h-20 flex items-center justify-center border border-dashed border-[#1f1f1f] rounded-lg text-gray-700 hover:text-gray-500 hover:border-[#2a2a2a] transition-all text-xs"
                    >
                      + Add
                    </button>
                  </div>
                </div>
              )}
            </Card>

            {/* Live Preview */}
            <Card>
              <SectionTitle>Live Preview</SectionTitle>
              <ProblemPreview details={details} desc={desc} testCases={testCases} />
            </Card>
          </div>
        )}

        {/* ── STEP 3: Test Cases ────────────────────────────────────────── */}
        {step === 3 && (
          <div className="space-y-4 animate-fade-in">

            {/* Stats + action bar */}
            <div className="flex items-center gap-3 bg-[#0e0e0e] border border-[#1a1a1a] rounded-xl px-5 py-3 flex-wrap">
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-red-500" />
                <span className="text-sm font-mono text-gray-400">
                  <span className="text-red-400 font-bold">{publicCount}</span> public
                </span>
              </div>
              <div className="w-px h-4 bg-[#1f1f1f]" />
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-gray-700" />
                <span className="text-sm font-mono text-gray-400">
                  <span className="text-gray-300 font-bold">{hiddenCount}</span> hidden
                </span>
              </div>
              <div className="w-px h-4 bg-[#1f1f1f]" />
              <span className="text-sm font-mono text-gray-600">{testCases.length} total</span>

              <div className="ml-auto flex items-center gap-2 flex-wrap">
                <button
                  onClick={() => setShowAI(true)}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-red-900/60 text-red-400 hover:bg-red-950/20 transition-all font-semibold"
                >
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                    <path d="M5 1l1.2 2.6L9 5 6.2 6.4 5 9 3.8 6.4 1 5l2.8-1.4z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
                  </svg>
                  AI Generate
                </button>
                <button
                  onClick={() => setShowBulk(true)}
                  className="text-xs px-3 py-1.5 rounded-lg border border-[#222] text-gray-500 hover:text-gray-300 hover:border-[#333] transition-all font-semibold"
                >
                  ↑ Bulk Import
                </button>
                <div className="w-px h-4 bg-[#1f1f1f]" />
                <button
                  onClick={() => addTC(true)}
                  className="text-xs px-3 py-1.5 rounded-lg border border-red-800/50 text-red-400 hover:bg-red-950/20 transition-all font-semibold"
                >
                  + Public
                </button>
                <button
                  onClick={() => addTC(false)}
                  className="text-xs px-3 py-1.5 rounded-lg border border-[#1f1f1f] text-gray-500 hover:text-gray-300 hover:border-[#2a2a2a] transition-all font-semibold"
                >
                  + Hidden
                </button>
                {hiddenCount > 0 && (
                  <button
                    onClick={clearAllHidden}
                    className="text-xs px-3 py-1.5 rounded-lg border border-[#1f1f1f] text-gray-700 hover:text-red-400 hover:border-red-900/50 transition-all font-semibold"
                  >
                    Clear Hidden
                  </button>
                )}
              </div>
            </div>

            {errors.testCases && (
              <p className="text-xs text-red-500 px-1 font-mono">{errors.testCases}</p>
            )}

            {/* Drag hint */}
            <p className="text-[10px] text-gray-700 font-mono px-1">
              Drag the ⠿ handle to reorder. First 2 public cases show as examples on the problem page.
            </p>

            {/* Test case list */}
            <div className="space-y-2">
              {testCases.map((tc, i) => (
                <div
                  key={i}
                  draggable
                  onDragStart={() => handleDragStart(i)}
                  onDragEnter={() => handleDragEnter(i)}
                  onDragEnd={handleDragEnd}
                  onDragOver={e => e.preventDefault()}
                  style={{
                    opacity: dragIdx === i ? 0.5 : 1,
                    outline: dragOver === i && dragIdx !== i ? '1px solid rgba(220,38,38,0.4)' : 'none',
                    borderRadius: 12,
                  }}
                >
                  <TestCaseRow
                    tc={tc}
                    idx={i}
                    onChange={val => updateTC(i, val)}
                    onRemove={() => removeTC(i)}
                    canRemove={testCases.length > 1}
                    isDragging={dragIdx === i}
                    dragHandleProps={{}}
                  />
                  {errors[`tc_${i}`] && (
                    <p className="text-xs text-red-500 mt-1 px-1 font-mono">{errors[`tc_${i}`]}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── STEP 4: Review ────────────────────────────────────────────── */}
        {step === 4 && (
          <div className="space-y-5 animate-fade-in">

            {/* Summary stats */}
            <div className="grid grid-cols-4 gap-3">
              {[
                { label: 'Total Tests', value: testCases.length, color: 'text-white' },
                { label: 'Public',      value: publicCount,      color: 'text-red-400' },
                { label: 'Hidden',      value: hiddenCount,      color: 'text-gray-300' },
                { label: 'Time Limit',  value: `${details.time_limit}ms`, color: 'text-gray-300' },
              ].map(({ label, value, color }) => (
                <div key={label} className="bg-[#0e0e0e] border border-[#1a1a1a] rounded-xl p-4 text-center">
                  <p className={`text-2xl font-bold font-mono ${color}`}>{value}</p>
                  <p className="text-[10px] uppercase tracking-widest text-gray-600 mt-1">{label}</p>
                </div>
              ))}
            </div> 

            {/* Live preview */}
            <Card>
              <SectionTitle>Problem Preview</SectionTitle>
              <ProblemPreview details={details} desc={desc} testCases={testCases} />
            </Card>

            {/* Test case quick list */}
            <Card>
              <SectionTitle>Test Cases Summary</SectionTitle>
              <div className="space-y-1.5">
                {testCases.map((tc, i) => (
                  <div key={i} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a]">
                    <span className="text-[10px] font-mono text-gray-700 w-8">#{String(i+1).padStart(2,'0')}</span>
                    <span className={cls(
                      'text-[9px] font-bold px-1.5 py-0.5 rounded border uppercase tracking-wider',
                      tc.is_sample ? 'text-red-400 border-red-800/50 bg-red-950/30' : 'text-gray-600 border-[#1f1f1f] bg-transparent'
                    )}>
                      {tc.is_sample ? 'pub' : 'hid'}
                    </span>
                    <span className="text-xs text-gray-600 font-mono truncate flex-1">
                      {tc.input.replace(/\n/g,' ').substring(0,40) || <em className="text-gray-800">empty</em>}
                    </span>
                    <span className="text-gray-700 text-xs">→</span>
                    <span className="text-xs text-gray-600 font-mono truncate max-w-[100px]">
                      {tc.expected_output.replace(/\n/g,' ').substring(0,20) || <em className="text-gray-800">empty</em>}
                    </span>
                    {(!tc.input.trim() || !tc.expected_output.trim()) && (
                      <span className="text-[9px] text-red-500 font-mono">⚠ empty</span>
                    )}
                  </div>
                ))}
              </div>
            </Card>

            {errors.submit && (
              <div className="flex items-center gap-2 text-sm text-red-400 bg-red-900/20 border border-red-900 rounded-lg px-4 py-3">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" className="flex-shrink-0">
                  <circle cx="7" cy="7" r="6" stroke="#f87171" strokeWidth="1.5"/>
                  <path d="M7 4v3" stroke="#f87171" strokeWidth="1.5" strokeLinecap="round"/>
                  <circle cx="7" cy="10" r="0.8" fill="#f87171"/>
                </svg>
                {errors.submit}
              </div>
            )}
          </div>
        )}

        {/* ── Navigation ──────────────────────────────────────────────────── */}
        <div className="flex items-center justify-between mt-8 pt-6 border-t border-[#161616]">
          <button
            onClick={() => step > 1 ? setStep(s => s - 1) : navigate('/problems')}
            className="flex items-center gap-2 px-5 py-2.5 rounded-lg border border-[#1f1f1f] text-gray-600 hover:text-gray-300 hover:border-[#2a2a2a] text-sm font-medium transition-all"
          >
            <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
              <path d="M8 2L3 6.5l5 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            {step === 1 ? 'Cancel' : 'Back'}
          </button>

          {/* Step progress */}
          <span className="text-[11px] font-mono text-gray-700">{step} / 4</span>

          {step < 4 ? (
            <button
              onClick={nextStep}
              className="flex items-center gap-2 px-6 py-2.5 rounded-lg bg-red-600 hover:bg-red-500 text-white text-sm font-semibold transition-all shadow-lg shadow-red-950/40"
            >
              Continue
              <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
                <path d="M5 2l5 4.5L5 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={submitting}
              className="flex items-center gap-2 px-6 py-2.5 rounded-lg bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-semibold transition-all shadow-lg shadow-red-950/40"
            >
              {submitting ? (
                <>
                  <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                  Publishing...
                </>
              ) : (
                <>
                  Publish Problem
                  <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
                    <path d="M2 6.5h9M7 2l4.5 4.5L7 11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </>
  )
}