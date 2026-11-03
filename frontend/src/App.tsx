import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";
import "./App.css";

const API = "/api";
type User = { id: number; email: string };
type Document = {
  id: number;
  filename: string;
  upload_date: string;
  processing_status: string;
  total_references: number;
  retracted_references: number;
};
type Finding = {
  reference_id: number;
  title: string | null;
  authors: string | null;
  year: number | null;
  doi: string | null;
  pmid: string | null;
  is_retracted: boolean | null;
  detection_method: string | null;
  retracted_publication: null | {
    title: string | null;
    doi: string | null;
    source: string | null;
    retraction_reason: string | null;
  };
};
type ApiError = { message?: string };

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    credentials: "include",
    ...init,
  });
  const payload = (await response.json().catch(() => ({}))) as T & ApiError;
  if (!response.ok)
    throw new Error(payload.message || `Request failed (${response.status})`);
  return payload;
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    async function initializeSession() {
      try {
        const result = await request<{ user: User }>("/me");
        if (active) setUser(result.user);
      } catch {
        if (active) setUser(null);
      } finally {
        if (active) setReady(true);
      }
    }

    void initializeSession();

    return () => {
      active = false;
    };
  }, []);

  async function authenticate(
    path: "/login" | "/register",
    email: string,
    password: string,
  ) {
    setError("");
    try {
      const csrf = await request<{ csrf_token: string }>("/csrf");
      const result = await request<{ user: User; csrf_token?: string }>(path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf.csrf_token,
        },
        body: JSON.stringify({ email, password }),
      });
      // Registration creates an account; login establishes the session.
      if (path === "/register") return true;
      setUser(result.user);
      return true;
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Something went wrong.",
      );
    }
    return false;
  }

  async function logout() {
    try {
      const csrf = await request<{ csrf_token: string }>("/csrf");
      await request("/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf.csrf_token },
      });
      setUser(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not log out.");
    }
  }

  if (!ready)
    return (
      <main className="center-screen">
        <p>Loading Retraction Checker…</p>
      </main>
    );
  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/login"
          element={
            user ? (
              <Navigate to="/" replace />
            ) : (
              <AuthPage
                mode="login"
                error={error}
                onSubmit={(e, p) => authenticate("/login", e, p)}
              />
            )
          }
        />
        <Route
          path="/register"
          element={
            user ? (
              <Navigate to="/" replace />
            ) : (
              <AuthPage
                mode="register"
                error={error}
                onSubmit={(e, p) => authenticate("/register", e, p)}
              />
            )
          }
        />
        <Route
          path="/"
          element={
            user ? (
              <Dashboard
                user={user}
                onLogout={logout}
                error={error}
                setError={setError}
              />
            ) : (
              <Navigate to="/login" replace />
            )
          }
        />
        <Route
          path="/documents/:id"
          element={user ? <ResultsPage /> : <Navigate to="/login" replace />}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

function AuthPage({
  mode,
  error,
  onSubmit,
}: {
  mode: "login" | "register";
  error: string;
  onSubmit: (email: string, password: string) => Promise<unknown>;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [localError, setLocalError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const registered = Boolean(
    (location.state as { registered?: boolean } | null)?.registered,
  );
  const registering = mode === "register";
  async function submit(event: FormEvent) {
    event.preventDefault();
    setLocalError("");
    setBusy(true);
    const result = await onSubmit(email, password);
    setBusy(false);
    if (result === true && registering)
      navigate("/login", { state: { registered: true } });
    else if (result === true) navigate("/");
    else setLocalError("Check the details and try again.");
  }
  return (
    <main className="auth-shell">
      <section className="auth-card">
        <Brand />
        <p className="eyebrow">RESEARCH INTEGRITY, MADE CLEAR</p>
        <h1>{registering ? "Create your account" : "Welcome back"}</h1>
        <p className="muted">
          {registering
            ? "Start checking your references for retraction notices."
            : "Sign in to review your document checks."}
        </p>
        <form onSubmit={submit} className="form-stack">
          <label>
            Email address
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete={registering ? "new-password" : "current-password"}
              minLength={8}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {registered && (
            <p className="success" role="status">
              Account created. Sign in to continue.
            </p>
          )}
          {(error || localError) && (
            <p className="alert" role="alert">
              {error || localError}
            </p>
          )}
          <button className="primary" disabled={busy}>
            {busy ? "Please wait…" : registering ? "Create account" : "Sign in"}
          </button>
        </form>
        <p className="auth-switch">
          {registering
            ? "Already have an account?"
            : "New to Retraction Checker?"}{" "}
          <Link to={registering ? "/login" : "/register"}>
            {registering ? "Sign in" : "Create an account"}
          </Link>
        </p>
      </section>
      <aside className="auth-aside">
        <div className="orb orb-one" />
        <div className="orb orb-two" />
        <p className="eyebrow">TRUST EVERY CITATION</p>
        <h2>Make confident decisions about the research you rely on.</h2>
        <p>
          Upload a paper and quickly see whether its references have been
          retracted.
        </p>
        <div className="aside-note">
          <span>✓</span> Your documents stay private to your account
        </div>
      </aside>
    </main>
  );
}

function Brand() {
  return (
    <Link className="brand" to="/">
      <span className="brand-mark">R</span>
      <span>
        Retraction<span className="brand-light">Checker</span>
      </span>
    </Link>
  );
}

function Dashboard({
  user,
  onLogout,
  error,
  setError,
}: {
  user: User;
  onLogout: () => void;
  error: string;
  setError: (value: string) => void;
}) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");
  const [uploadError, setUploadError] = useState("");
  const load = useCallback(async () => {
    try {
      const data = await request<{ documents: Document[] }>("/documents");
      setDocuments(data.documents);
    } catch (cause) {
      setUploadError(
        cause instanceof Error ? cause.message : "Could not load documents.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;

    async function loadInitialDocuments() {
      try {
        const data = await request<{ documents: Document[] }>("/documents");

        if (active) {
          setDocuments(data.documents);
        }
      } catch (cause) {
        if (active) {
          setUploadError(
            cause instanceof Error
              ? cause.message
              : "Could not load documents.",
          );
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void loadInitialDocuments();

    return () => {
      active = false;
    };
  }, []);
  async function upload(file?: File) {
    if (!file) return;
    setUploadError("");
    setMessage("");
    setError("");
    setUploading(true);
    try {
      const csrf = await request<{ csrf_token: string }>("/csrf");
      const body = new FormData();
      body.append("file", file);
      const result = await request<{
        filename: string;
        references_processed: number;
        retracted_references: number;
      }>("/analyze", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf.csrf_token },
        body,
      });
      setMessage(
        `Checked ${result.filename}: ${result.references_processed} references, ${result.retracted_references} retracted.`,
      );
      await load();
    } catch (cause) {
      setUploadError(cause instanceof Error ? cause.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }
  return (
    <div className="app-shell">
      <header className="topbar">
        <Brand />
        <div className="account">
          <span>{user.email}</span>
          <button className="quiet-button" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </header>
      <main className="dashboard">
        <div className="welcome">
          <div>
            <p className="eyebrow">YOUR WORKSPACE</p>
            <h1>Reference checks</h1>
            <p className="muted">
              Find out whether the sources in your paper have been retracted.
            </p>
          </div>
          <div className="welcome-icon">⌕</div>
        </div>
        <section className="upload-panel">
          <div className="upload-copy">
            <span className="upload-icon">↑</span>
            <div>
              <h2>Check a paper</h2>
              <p>Upload a PDF to extract and check its references.</p>
            </div>
          </div>
          <label className={`upload-button ${uploading ? "disabled" : ""}`}>
            {uploading ? "Analyzing PDF…" : "Choose a PDF"}
            <input
              type="file"
              accept="application/pdf,.pdf"
              disabled={uploading}
              onChange={(e) => {
                void upload(e.target.files?.[0]);
                e.currentTarget.value = "";
              }}
            />
          </label>
          <small>PDF files only · Maximum 16 MB</small>
          {message && (
            <p className="success" role="status">
              {message}
            </p>
          )}
          {(uploadError || error) && (
            <p className="alert" role="alert">
              {uploadError || error}
            </p>
          )}
        </section>
        <section className="history">
          <div className="section-heading">
            <div>
              <p className="eyebrow">RECENT ACTIVITY</p>
              <h2>Your documents</h2>
            </div>
            <span className="count-pill">
              {documents.length}{" "}
              {documents.length === 1 ? "document" : "documents"}
            </span>
          </div>
          {loading ? (
            <p className="empty-state">Loading your documents…</p>
          ) : documents.length === 0 ? (
            <div className="empty-state">
              <span className="empty-icon">▤</span>
              <h3>No checks yet</h3>
              <p>Your analyzed papers will appear here.</p>
            </div>
          ) : (
            <div className="document-list">
              {documents.map((doc) => (
                <Link
                  className="document-row"
                  to={`/documents/${doc.id}`}
                  key={doc.id}
                >
                  <span className="pdf-icon">PDF</span>
                  <span className="document-name">
                    <strong>{doc.filename}</strong>
                    <small>
                      {new Date(doc.upload_date).toLocaleDateString()} ·{" "}
                      {doc.total_references} references
                    </small>
                  </span>
                  <span
                    className={
                      doc.retracted_references
                        ? "result-badge warning"
                        : "result-badge clear"
                    }
                  >
                    {doc.retracted_references
                      ? `${doc.retracted_references} retracted`
                      : "No retractions"}
                  </span>
                  <span className="row-arrow">→</span>
                </Link>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}

function ResultsPage() {
  const { id } = useParams();
  const [data, setData] = useState<{
    document: Document;
    total_references: number;
    retracted_references: number;
    results: Finding[];
  } | null>(null);
  const [error, setError] = useState("");
  const [onlyRetracted, setOnlyRetracted] = useState(false);
  useEffect(() => {
    let alive = true;
    request<typeof data>(`/documents/${id}/results`)
      .then((result) => {
        if (alive) setData(result);
      })
      .catch((cause) => {
        if (alive)
          setError(
            cause instanceof Error ? cause.message : "Could not load results.",
          );
      });
    return () => {
      alive = false;
    };
  }, [id]);
  if (error)
    return (
      <div className="app-shell">
        <header className="topbar">
          <Brand />
        </header>
        <main className="dashboard">
          <Link to="/" className="back-link">
            ← Back to documents
          </Link>
          <p className="alert">{error}</p>
        </main>
      </div>
    );
  if (!data) return <main className="center-screen">Loading results…</main>;
  const findings = data.results.filter(
    (item) => !onlyRetracted || item.is_retracted === true,
  );
  return (
    <div className="app-shell">
      <header className="topbar">
        <Brand />
      </header>
      <main className="dashboard">
        <Link to="/" className="back-link">
          ← All documents
        </Link>
        <p className="eyebrow">ANALYSIS REPORT</p>
        <h1 className="result-title">{data.document.filename}</h1>
        <p className="muted">
          Analyzed {new Date(data.document.upload_date).toLocaleString()}
        </p>
        <section className="summary-grid">
          <div className="summary-card">
            <span>References checked</span>
            <strong>{data.total_references}</strong>
          </div>
          <div
            className={`summary-card ${data.retracted_references ? "summary-warning" : "summary-clear"}`}
          >
            <span>Retracted references</span>
            <strong>{data.retracted_references}</strong>
          </div>
        </section>
        <div className="section-heading result-heading">
          <div>
            <p className="eyebrow">REFERENCE DETAILS</p>
            <h2>Findings</h2>
          </div>
          <label className="filter-toggle">
            <input
              type="checkbox"
              checked={onlyRetracted}
              onChange={(e) => setOnlyRetracted(e.target.checked)}
            />{" "}
            Retracted only
          </label>
        </div>
        <div className="finding-list">
          {findings.map((item) => (
            <article className="finding-card" key={item.reference_id}>
              <div className="finding-top">
                <div>
                  <h3>{item.title || "Untitled reference"}</h3>
                  <p>
                    {item.authors || "Authors unavailable"}
                    {item.year ? ` · ${item.year}` : ""}
                  </p>
                </div>
                <span
                  className={`result-badge ${item.is_retracted ? "warning" : item.is_retracted === false ? "clear" : "unknown"}`}
                >
                  {item.is_retracted
                    ? "Retracted"
                    : item.is_retracted === false
                      ? "No retraction found"
                      : "Not verified"}
                </span>
              </div>
              {item.doi && (
                <p className="metadata">
                  <b>DOI</b> {item.doi}
                </p>
              )}
              {item.pmid && (
                <p className="metadata">
                  <b>PMID</b> {item.pmid}
                </p>
              )}
              {item.retracted_publication && (
                <div className="retraction-info">
                  <strong>Retraction notice</strong>
                  {item.retracted_publication.title && (
                    <p>{item.retracted_publication.title}</p>
                  )}
                  {item.retracted_publication.retraction_reason && (
                    <p>
                      Reason: {item.retracted_publication.retraction_reason}
                    </p>
                  )}
                  <small>
                    {item.retracted_publication.source || item.detection_method}
                  </small>
                </div>
              )}
            </article>
          ))}
          {findings.length === 0 && (
            <p className="empty-state">No references match this filter.</p>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
