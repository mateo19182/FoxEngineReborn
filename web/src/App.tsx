import { useEffect, useState } from "react";
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { api, getToken, setToken } from "./api";
import { AdminPage } from "./AdminPage";
import { AccountPage } from "./AccountPage";
import { IngestPage } from "./IngestPage";
import { JobsPage } from "./JobsPage";
import { LoginPage } from "./LoginPage";
import { QueryPage } from "./QueryPage";
import { SetupPage } from "./SetupPage";
import { StoragePage } from "./StoragePage";
import { AssistantChatWidget } from "./AssistantChatWidget";
import { canIngest } from "./roles";

function Shell({ children }: { children: React.ReactNode }) {
  const [roles, setRoles] = useState<string[]>([]);
  const [llmOn, setLlmOn] = useState(false);

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

  const operator = canIngest(roles);

  return (
    <>
      <header className="site-header">
        <div className="layout site-header__row">
          <Link className="brand" to="/query">
            FoxEngine
          </Link>
          <NavLink
            to="/query"
            className={({ isActive }) => `nav-link${isActive ? " nav-link--active" : ""}`}
          >
            Query
          </NavLink>
          {operator ? (
            <NavLink
              to="/ingest"
              className={({ isActive }) => `nav-link${isActive ? " nav-link--active" : ""}`}
            >
              Ingest
            </NavLink>
          ) : null}
          {operator ? (
            <NavLink
              to="/storage"
              className={({ isActive }) => `nav-link${isActive ? " nav-link--active" : ""}`}
            >
              Storage
            </NavLink>
          ) : null}
          <NavLink
            to="/jobs"
            className={({ isActive }) => `nav-link${isActive ? " nav-link--active" : ""}`}
          >
            Jobs
          </NavLink>
          {roles.includes("admin") ? (
            <NavLink
              to="/admin"
              className={({ isActive }) => `nav-link${isActive ? " nav-link--active" : ""}`}
            >
              Admin
            </NavLink>
          ) : (
            <NavLink
              to="/account"
              className={({ isActive }) => `nav-link${isActive ? " nav-link--active" : ""}`}
            >
              Account
            </NavLink>
          )}
          <span className="nav-gap" />
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setToken(null);
              window.location.href = "/login";
            }}
          >
            Log out
          </button>
        </div>
      </header>
      <main className="layout main-area">{children}</main>
      {llmOn ? <AssistantChatWidget /> : null}
    </>
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
      <Route path="/tags" element={<Navigate to="/query" replace />} />
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
