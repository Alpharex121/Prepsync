import { NavLink } from "react-router-dom";

import { useAuth } from "../context/AuthContext";

export default function Navbar() {
  const { isAuthenticated, user, logout } = useAuth();

  return (
    <header className="navbar">
      <h1 className="brand">PrepSync</h1>
      <nav className="nav-links">
        <NavLink to="/" className="nav-link">
          Home
        </NavLink>

        {isAuthenticated ? (
          <>
            <NavLink to="/room" className="nav-link">
              Room
            </NavLink>
            <NavLink to="/history" className="nav-link">
              History
            </NavLink>
            <NavLink to="/profile" className="nav-link">
              {user?.username}
            </NavLink>
            <button type="button" className="logout-btn" onClick={logout}>
              Logout
            </button>
          </>
        ) : (
          <NavLink to="/login" className="nav-link">
            Login
          </NavLink>
        )}
      </nav>
    </header>
  );
}
