import { Routes, Route, Navigate } from 'react-router-dom'
import Navbar from './components/Navbar'
import Login from './pages/Login'
import Register from './pages/Register'
import Problems from './pages/Problems'
import Problem from './pages/Problem'
import AdminPanel from './pages/Adminpanel'
import Verdict from './pages/Verdict'

export default function App() {
  return (
    <div className="min-h-screen bg-bg">
      <Navbar />
      <Routes>
        <Route path="/"                   element={<Navigate to="/problems" />} />
        <Route path="/login"              element={<Login />} />
        <Route path="/register"           element={<Register />} />
        <Route path="/problems"           element={<Problems />} />
        <Route path="/problems/:slug"     element={<Problem />} />
        <Route path="/admin"              element={<AdminPanel />} />
        <Route path="/verdict/:id"        element={<Verdict />} />
      </Routes>
    </div>
  )
}