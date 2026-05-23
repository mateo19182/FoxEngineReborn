import { useEffect, useState } from "react";
import {
  BrowserRouter,
  Link,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { api, getToken, logout } from "./api";
import { AdminPage } from "./AdminPage";
import { AccountPage } from "./AccountPage";
import { IngestPage } from "./IngestPage";
import { JobsPage } from "./JobsPage";
import { LoginPage } from "./LoginPage";
import { QueryPage } from "./QueryPage";
import { TagsPage } from "./TagsPage";
import { SetupPage } from "./SetupPage";
import { StoragePage } from "./StoragePage";
import { AssistantChatWidget } from "./AssistantChatWidget";
import { InformaticEyeMark } from "./InformaticEyeMark";
import { canIngest } from "./roles";

function Shell({ children }: { children: React.ReactNode }) {
  const [roles, setRoles] = useState<string[]>([]);
  const [llmOn, setLlmOn] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    api<{ roles: string[]; llm_nl_enabled?: boolean }>("/auth/me")
      .then((m) => {
        setRoles(m.roles);
        setLlmOn(m.llm_nl_enabled !== false);
      })
      .catch(() => {
        setRoles([]);
        setLlmOn(false);
      });
  }, []);

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 769px)");
    const onChange = () => {
      if (mq.matches) {
        setSidebarOpen(false);
      }
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (!sidebarOpen) {
      return;
    }
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [sidebarOpen]);

  const operator = canIngest(roles);

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    `sidebar-nav__link${isActive ? " sidebar-nav__link--active" : ""}`;

  return (
    <div className="app-shell">
      <button
        type="button"
        className={`app-shell__menu-btn${sidebarOpen ? " app-shell__menu-btn--open" : ""}`}
        aria-expanded={sidebarOpen}
        aria-controls="app-sidebar"
        aria-label={sidebarOpen ? "Close menu" : "Open menu"}
        onClick={() => setSidebarOpen((o) => !o)}
      >
        <span className="app-shell__menu-btn-bar" />
        <span className="app-shell__menu-btn-bar" />
        <span className="app-shell__menu-btn-bar" />
      </button>
      {sidebarOpen ? (
        <button
          type="button"
          className="app-shell__scrim"
          aria-label="Close menu"
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}
      <aside
        id="app-sidebar"
        className={`app-sidebar${sidebarOpen ? " app-sidebar--open" : ""}`}
      >
        <div className="app-sidebar__glow" aria-hidden />
        <div className="app-sidebar__top">
          <Link className="sidebar-brand" to="/query" onClick={() => setSidebarOpen(false)}>
            <span className="sidebar-brand__mark" aria-hidden>
              <InformaticEyeMark />
            </span>
            <span className="sidebar-brand__word">FoxEngine</span>
          </Link>
        </div>
        <nav className="sidebar-nav" aria-label="Primary">
          <NavLink to="/query" className={linkClass} end>
            Query
          </NavLink>
          <NavLink to="/tags" className={linkClass}>
            Tags
          </NavLink>
          {operator ? (
            <NavLink to="/ingest" className={linkClass}>
              Ingest
            </NavLink>
          ) : null}
          {operator ? (
            <NavLink to="/storage" className={linkClass}>
              Storage
            </NavLink>
          ) : null}
          <NavLink to="/jobs" className={linkClass}>
            Jobs
          </NavLink>
          {roles.includes("admin") ? (
            <NavLink to="/admin" className={linkClass}>
              Admin
            </NavLink>
          ) : (
            <NavLink to="/account" className={linkClass}>
              Account
            </NavLink>
          )}
        </nav>
        <div className="app-sidebar__spacer" />
        <div className="app-sidebar__foot">
          <button type="button" className="sidebar-logout" onClick={logout}>
            Log out
          </button>
        </div>
      </aside>
      <div className="app-shell__main">
        <main className="layout main-area">{children}</main>
      </div>
      {llmOn ? <AssistantChatWidget /> : null}
    </div>
  );
}

function RequireOperator({ children }: { children: React.ReactNode }) {
  const token = getToken();
  const [ok, setOk] = useState<boolean | null>(null);

  useEffect(() => {
    if (!token) {
      return;
    }
    api<{ roles: string[] }>("/auth/me")
      .then((m) => setOk(canIngest(m.roles)))
      .catch(() => setOk(false));
  }, [token]);

  if (!token) return <Navigate to="/login" replace />;
  if (ok === null) {
    return (
      <div className="layout main-area">
        <p className="muted">Loading…</p>
      </div>
    );
  }
  if (!ok) return <Navigate to="/query" replace />;
  return <Shell>{children}</Shell>;
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = getToken();
  if (!token) return <Navigate to="/login" replace />;
  return <Shell>{children}</Shell>;
}

function AccountRedirect() {
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null);

  useEffect(() => {
    api<{ roles: string[] }>("/auth/me")
      .then((m) => setIsAdmin(m.roles.includes("admin")))
      .catch(() => setIsAdmin(false));
  }, []);

  if (isAdmin === null) {
    return <p className="muted">Loading…</p>;
  }
  if (isAdmin) {
    return <Navigate to="/admin" replace />;
  }
  return <AccountPage />;
}

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const token = getToken();
  const [ok, setOk] = useState<boolean | null>(null);

  useEffect(() => {
    if (!token) {
      return;
    }
    api<{ roles: string[] }>("/auth/me")
      .then((m) => setOk(m.roles.includes("admin")))
      .catch(() => setOk(false));
  }, [token]);

  if (!token) return <Navigate to="/login" replace />;
  if (ok === null) {
    return (
      <div className="layout main-area">
        <p className="muted">Loading…</p>
      </div>
    );
  }
  if (!ok) return <Navigate to="/query" replace />;
  return <Shell>{children}</Shell>;
}

function AppRoutes() {
  const [phase, setPhase] = useState<"loading" | "setup" | "app">("loading");
  const nav = useNavigate();

  useEffect(() => {
    (async () => {
      try {
        const s = await api<{ needs_setup: boolean }>("/setup/status");
        setPhase(s.needs_setup ? "setup" : "app");
      } catch {
        setPhase("app");
      }
    })();
  }, []);

  if (phase === "loading") {
    return (
      <div className="layout main-area">
        <p className="muted">Loading…</p>
      </div>
    );
  }

  if (phase === "setup") {
    return (
      <SetupPage
        onDone={() => {
          setPhase("app");
          nav("/login");
        }}
      />
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage onLoggedIn={() => nav("/query")} />} />
      <Route
        path="/query"
        element={
          <RequireAuth>
            <QueryPage />
          </RequireAuth>
        }
      />
      <Route
        path="/tags"
        element={
          <RequireAuth>
            <TagsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/ingest"
        element={
          <RequireOperator>
            <IngestPage />
          </RequireOperator>
        }
      />
      <Route
        path="/storage"
        element={
          <RequireOperator>
            <StoragePage />
          </RequireOperator>
        }
      />
      <Route
        path="/jobs"
        element={
          <RequireAuth>
            <JobsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/account"
        element={
          <RequireAuth>
            <AccountRedirect />
          </RequireAuth>
        }
      />
      <Route
        path="/admin"
        element={
          <RequireAdmin>
            <AdminPage />
          </RequireAdmin>
        }
      />
      <Route path="/" element={<Navigate to={getToken() ? "/query" : "/login"} replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
