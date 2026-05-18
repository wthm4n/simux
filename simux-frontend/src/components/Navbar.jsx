import { Link, useNavigate, useLocation } from "react-router-dom";

export default function Navbar() {
  const navigate = useNavigate();
  const location = useLocation();
  const token = localStorage.getItem("token");
  const username = localStorage.getItem("username");
  const role = localStorage.getItem("role");

  function logout() {
    localStorage.clear();
    navigate("/login");
  }

  return (
    <nav className="sticky top-0 z-50 bg-surface/80 backdrop-blur-md border-b border-border">
      <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
        {/* Logo */}
        <Link to="/problems" className="flex items-center gap-2 group">
          <span className="w-6 h-6 rounded bg-red-600 flex items-center justify-center">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path
                d="M2 10L6 2L10 10"
                stroke="white"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M3.5 7h5"
                stroke="white"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </svg>
          </span>
          <span className="font-mono font-semibold text-sm tracking-tight">
            <span className="text-white">simux</span>
            <span className="text-red-500">judge</span>
          </span>
        </Link>

        {/* Nav links */}
        {/* Nav links */}
        <div className="flex items-center gap-1">
          <Link
            to="/problems"
            className={`px-3 py-1.5 rounded text-sm transition-colors font-medium ${
              location.pathname.startsWith("/problems")
                ? "text-white bg-white/5"
                : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
            }`}
          >
            Problems
          </Link>

          {role === "admin" && (
            <Link
              to="/admin"
              className={`px-3 py-1.5 rounded text-sm transition-colors font-medium ${
                location.pathname.startsWith("/admin")
                  ? "text-white bg-white/5"
                  : "text-gray-500 hover:text-gray-300 hover:bg-white/5"
              }`}
            >
              Admin
            </Link>
          )}
        </div>

        {/* Auth */}
        <div className="flex items-center gap-3">
          {token ? (
            <>
              {role === "admin" && (
                <span className="text-[10px] font-mono uppercase tracking-widest text-red-500 border border-red-800 px-2 py-0.5 rounded">
                  admin
                </span>
              )}
              <span className="text-sm text-gray-500 font-mono">
                @{username}
              </span>
              <button
                onClick={logout}
                className="text-sm text-gray-500 hover:text-red-400 transition-colors"
              >
                Logout
              </button>
            </>
          ) : (
            <>
              <Link
                to="/login"
                className="text-sm text-gray-400 hover:text-white transition-colors"
              >
                Login
              </Link>
              <Link
                to="/register"
                className="text-sm bg-red-600 hover:bg-red-500 text-white px-4 py-1.5 rounded-md transition-colors font-medium"
              >
                Register
              </Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
