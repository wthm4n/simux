import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import axios from "axios";

const API = "http://localhost:3000";

const VERDICT_MAP = {
  AC: {
    label: "Accepted",
    color: "text-emerald-400",
    bg: "bg-emerald-950/40 border-emerald-800",
    dot: "#34d399",
  },
  WA: {
    label: "Wrong Answer",
    color: "text-red-400",
    bg: "bg-red-950/40 border-red-800",
    dot: "#f87171",
  },
  TLE: {
    label: "Time Limit Exceeded",
    color: "text-amber-400",
    bg: "bg-amber-950/40 border-amber-800",
    dot: "#fbbf24",
  },
  RE: {
    label: "Runtime Error",
    color: "text-orange-400",
    bg: "bg-orange-950/40 border-orange-800",
    dot: "#fb923c",
  },
  SE: {
    label: "System Error",
    color: "text-gray-400",
    bg: "bg-gray-900/40 border-gray-700",
    dot: "#9ca3af",
  },
};

function VerdictIcon({ verdict }) {
  if (verdict === "AC")
    return (
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
        <circle cx="24" cy="24" r="23" stroke="#34d399" strokeWidth="2" />
        <path
          d="M14 24l7 7 13-13"
          stroke="#34d399"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  if (verdict === "WA")
    return (
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
        <circle cx="24" cy="24" r="23" stroke="#f87171" strokeWidth="2" />
        <path
          d="M16 16l16 16M32 16l-16 16"
          stroke="#f87171"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
    );
  if (verdict === "TLE")
    return (
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
        <circle cx="24" cy="24" r="23" stroke="#fbbf24" strokeWidth="2" />
        <path
          d="M24 14v10l6 6"
          stroke="#fbbf24"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  return (
    <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
      <circle cx="24" cy="24" r="23" stroke="#fb923c" strokeWidth="2" />
      <path
        d="M24 15v13M24 33v2"
        stroke="#fb923c"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function Verdict() {
  const { id } = useParams();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let interval;
    async function poll() {
      try {
        const res = await axios.get(`${API}/verdict/${id}`);
        setData(res.data);
        if (res.data.status === "done") {
          clearInterval(interval);
          setLoading(false);
        }
      } catch {
        clearInterval(interval);
        setLoading(false);
      }
    }
    poll();
    interval = setInterval(poll, 1500);
    return () => clearInterval(interval);
  }, [id]);

  const v = data?.verdict ? VERDICT_MAP[data.verdict] : null;
  const isDone = data?.status === "done";

  return (
    <div className="flex items-center justify-center min-h-[calc(100vh-56px)] px-4">
      <div className="w-full max-w-md animate-slide-up">
        <div className="bg-card border border-border rounded-2xl p-8">
          {/* Icon + verdict */}
          <div className="flex flex-col items-center text-center mb-8">
            <div className="mb-4">
              {!isDone ? (
                <div className="w-12 h-12 rounded-full border-2 border-red-600 border-t-transparent animate-spin" />
              ) : (
                <VerdictIcon verdict={data.verdict} />
              )}
            </div>

            {!isDone ? (
              <>
                <p className="text-xl font-bold text-gray-200">Judging...</p>
                <p className="text-sm text-gray-600 mt-1">
                  Running your code against test cases
                </p>
              </>
            ) : (
              <>
                <p className={`text-3xl font-bold ${v?.color}`}>{v?.label}</p>
                {data.time_ms > 0 && (
                  <p className="text-sm text-gray-500 font-mono mt-1">
                    {data.time_ms}ms
                  </p>
                )}
              </>
            )}
          </div>

          {/* Verdict badge */}
          {isDone && v && (
            <div
              className={`rounded-xl border px-5 py-3 mb-6 flex items-center justify-between ${v.bg}`}
            >
              <div className="flex items-center gap-2">
                <span
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ background: v.dot }}
                />
                <span className={`font-mono text-sm font-semibold ${v.color}`}>
                  {data.verdict}
                </span>
              </div>
              <span className={`text-sm ${v.color} opacity-70`}>{v.label}</span>
            </div>
          )}

          {/* Meta grid */}
          {data && (
            <div className="grid grid-cols-2 gap-3 mb-6">
              <div className="bg-surface rounded-lg px-4 py-3">
                <p className="text-[10px] uppercase tracking-widest text-gray-600 font-semibold mb-1">
                  Language
                </p>
                <p className="text-sm font-mono text-gray-200">
                  {data.language}
                </p>
              </div>
              <div className="bg-surface rounded-lg px-4 py-3">
                <p className="text-[10px] uppercase tracking-widest text-gray-600 font-semibold mb-1">
                  Runtime
                </p>
                <p className="text-sm font-mono text-gray-200">
                  {data.time_ms ? `${data.time_ms}ms` : "—"}
                </p>
              </div>
              <div className="bg-surface rounded-lg px-4 py-3 col-span-2">
                <p className="text-[10px] uppercase tracking-widest text-gray-600 font-semibold mb-1">
                  Submission ID
                </p>
                <p className="text-xs font-mono text-gray-400 truncate">{id}</p>
              </div>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3">
            <Link
              to="/problems"
              className="flex-1 text-center bg-surface hover:bg-muted border border-border text-gray-300 py-2.5 rounded-lg text-sm font-medium transition-colors"
            >
              All Problems
            </Link>
            {data?.problem_id && (
              <button
                onClick={() => window.history.back()}
                className="flex-1 text-center bg-red-600 hover:bg-red-500 text-white py-2.5 rounded-lg text-sm font-medium transition-colors"
              >
                Try Again
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
