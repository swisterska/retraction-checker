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
  useSearchParams,
} from "react-router-dom";
import "./App.css";
import "./dialog.css";
import "./verification-note.css";
import { filterFindings } from "./resultsFilter";
import type { ResultsFilter } from "./resultsFilter";

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
type AnalysisReport = {
  document: {
    id: number | string;
    filename: string;
    upload_date: string;
    processing_status: string;
  };
  total_references: number;
  retracted_references: number;
  results: Finding[];
};
type Finding = {
  reference_id: number;
  title: string | null;
  authors: string | null;
  year: number | null;
  doi: string | null;
  pmid: string | null;
  is_retracted: boolean | null;
  verification_status:
    | "retracted"
    | "verified"
    | "not_verified"
    | "missing_doi";
  verification_note: string | null;
  detection_method: string | null;
  retracted_publication: null | {
    title: string | null;
    doi: string | null;
    source: string | null;
    retraction_reason: string | null;
  };
};
type ApiErrorPayload = { code?: string; message?: string };

function verificationLabel(status: Finding["verification_status"]): string {
  switch (status) {
    case "retracted":
      return "Retracted";
    case "verified":
      return "Verified";
    case "missing_doi":
      return "Missing DOI";
    case "not_verified":
      return "No retraction notice found";
    default:
      return "No retraction notice found";
  }
}

function verificationInfo(status: Finding["verification_status"]): string {
  switch (status) {
    case "retracted":
      return "This reference is listed as retracted in Retraction Watch.";
    case "verified":
      return "This reference was found in Retraction Watch and matched the citation.";
    case "missing_doi":
      return "No DOI was available, so this reference could not be checked automatically.";
    case "not_verified":
      return "No active retraction notice was found in Retraction Watch. This reference is not flagged, but it should still be reviewed if the citation or DOI is uncertain.";
    default:
      return "No active retraction notice was found in Retraction Watch. This reference is not flagged, but it should still be reviewed if the citation or DOI is uncertain.";
  }
}

function verificationClass(status: Finding["verification_status"]): string {
  switch (status) {
    case "retracted":
      return "warning";
    case "verified":
      return "clear";
    case "missing_doi":
      return "missing";
    case "not_verified":
      return "clear";
    default:
      return "clear";
  }
}

class ApiRequestError extends Error {
  status: number;
  code?: string;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.message || `Request failed (${status})`);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = payload.code;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    credentials: "include",
    ...init,
  });
  const isJson = response.headers
    .get("content-type")
    ?.includes("application/json");
  const payload = (
    isJson
      ? await response.json().catch(() => ({}))
      : response.status === 404
        ? {
            message:
              "The server does not recognize this route. Restart Flask from the thesis project folder, then reload the page.",
          }
        : {}
  ) as T & ApiErrorPayload;
  if (!response.ok) throw new ApiRequestError(response.status, payload);
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
  ): Promise<boolean | "email_unverified"> {
    setError("");
    try {
      const csrf = await request<{ csrf_token: string }>("/csrf");
      const result = await request<{ user?: User; csrf_token?: string }>(path, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf.csrf_token,
        },
        body: JSON.stringify({ email, password }),
      });
      // Registration creates an account; login establishes the session.
      if (path === "/register") return true;
      if (result.user) setUser(result.user);
      return true;
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Something went wrong.",
      );
      if (
        cause instanceof ApiRequestError &&
        cause.code === "EMAIL_NOT_VERIFIED"
      )
        return "email_unverified";
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
        <Route path="/verify-email" element={<VerifyEmailPage />} />
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
              <LandingPage />
            )
          }
        />
        <Route path="/try" element={<GuestPage />} />
        <Route path="/guest/reports/:id" element={<ResultsPage guest />} />
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
  onSubmit: (
    email: string,
    password: string,
  ) => Promise<boolean | "email_unverified">;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [localError, setLocalError] = useState("");
  const [busy, setBusy] = useState(false);
  const [resending, setResending] = useState(false);
  const [resendMessage, setResendMessage] = useState("");
  const [needsVerification, setNeedsVerification] = useState(false);
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
    else if (result === "email_unverified") setNeedsVerification(true);
    else setLocalError("Check the details and try again.");
  }
  async function resendVerification() {
    setResending(true);
    setResendMessage("");
    try {
      const csrf = await request<{ csrf_token: string }>("/csrf");
      const result = await request<{ message: string }>(
        "/resend-verification",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf.csrf_token,
          },
          body: JSON.stringify({ email }),
        },
      );
      setResendMessage(result.message);
    } catch (cause) {
      setResendMessage(
        cause instanceof Error ? cause.message : "Could not resend the link.",
      );
    } finally {
      setResending(false);
    }
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
              Account saved. Check your email and click the confirmation link
              before signing in.
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
          {needsVerification && (
            <div>
              <button
                className="quiet-button"
                type="button"
                disabled={resending || !email}
                onClick={() => void resendVerification()}
              >
                {resending ? "Sending…" : "Resend confirmation link"}
              </button>
              {resendMessage && (
                <p className="success" role="status">
                  {resendMessage}
                </p>
              )}
            </div>
          )}
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

function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") || "";
  const [status, setStatus] = useState<"loading" | "success" | "error">(
    "loading",
  );
  const [message, setMessage] = useState("Confirming your email address…");

  useEffect(() => {
    let active = true;
    async function confirm() {
      if (!token) {
        setStatus("error");
        setMessage("This confirmation link is missing its token.");
        return;
      }
      try {
        const csrf = await request<{ csrf_token: string }>("/csrf");
        const result = await request<{ message: string }>("/verify-email", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf.csrf_token,
          },
          body: JSON.stringify({ token }),
        });
        if (active) {
          setStatus("success");
          setMessage(result.message);
        }
      } catch (cause) {
        if (active) {
          setStatus("error");
          setMessage(
            cause instanceof Error
              ? cause.message
              : "Could not confirm this email.",
          );
        }
      }
    }
    void confirm();
    return () => {
      active = false;
    };
  }, [token]);

  return (
    <main className="center-screen">
      <section className="verify-email-card">
        <Brand />
        <h1>
          {status === "success"
            ? "Email confirmed"
            : status === "error"
              ? "Confirmation link unavailable"
              : "Confirming your email"}
        </h1>
        <p>{message}</p>
        {status === "success" && (
          <Link className="primary verify-login-link" to="/login">
            Go to sign in
          </Link>
        )}
        {status === "error" && (
          <Link className="back-link" to="/login">
            Back to sign in
          </Link>
        )}
      </section>
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

function LandingPage() {
  return (
    <div className="app-shell landing-shell">
      <header className="topbar">
        <Brand />
        <Link className="quiet-button" to="/login">
          Sign in
        </Link>
      </header>
      <main className="landing-main">
        <section className="landing-hero">
          <div className="landing-copy">
            <p className="eyebrow">RETRACTION CHECKER</p>
            <h1>Check references in a research paper.</h1>
            <p className="landing-lede">
              Upload a PDF to see which references may have a retraction notice.
              Review the details before deciding what they mean for your work.
            </p>
            <div className="landing-actions">
              <Link className="primary landing-primary" to="/try">
                Try without an account <span aria-hidden="true">→</span>
              </Link>
              <Link className="secondary-action" to="/login">
                Sign in to your account
              </Link>
            </div>
            <p className="landing-footnote">
              Guest reports are temporary. Sign in to keep reports in your
              history.
            </p>
          </div>
          <div className="landing-visual landing-steps">
            <h2>What the report shows</h2>
            <ul>
              <li>References extracted from the PDF</li>
              <li>Matches found in the retraction data</li>
              <li>References that could not be confirmed</li>
            </ul>
            <p>
              Results should be checked against the linked publication details.
            </p>
          </div>
        </section>
        <p className="landing-note">
          This tool helps identify possible retraction notices; it does not
          assess the quality or reliability of a paper.
        </p>
      </main>
    </div>
  );
}

function GuestPage() {
  const [csrfToken, setCsrfToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    let active = true;
    request<{ csrf_token: string }>("/csrf")
      .then((result) => {
        if (active) setCsrfToken(result.csrf_token);
      })
      .catch((cause) => {
        if (active)
          setError(
            cause instanceof Error
              ? cause.message
              : "Could not start a guest session.",
          );
      });
    return () => {
      active = false;
    };
  }, []);

  async function analyze(file?: File) {
    if (!file || !csrfToken) return;
    setError("");
    setBusy(true);
    try {
      const body = new FormData();
      body.append("file", file);
      body.append("email", email);
      const result = await request<{ report_id: string }>("/guest/jobs", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
        body,
      });
      navigate(`/guest/reports/${result.report_id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Analysis failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <Brand />
        <Link className="quiet-button" to="/login">
          Sign in
        </Link>
      </header>
      <main className="guest-main">
        <Link className="back-link" to="/">
          ← Back
        </Link>
        <p className="eyebrow">GUEST CHECK</p>
        <h1>Try one reference check</h1>
        <p className="muted guest-intro">
          Upload a PDF and review its references. Your report is temporary and
          available for 48 hours. We’ll email a report link if email delivery is
          set up.
        </p>
        <section className="guest-upload-card">
          <span className="upload-icon">↑</span>
          <h2>
            {busy ? "Checking your references…" : "Choose a research paper"}
          </h2>
          <p>PDF only · Maximum file size 16 MB</p>
          <label className="guest-email-field">
            Email for the report link
            <input
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              required
            />
          </label>
          <label
            className={`upload-button ${busy || !csrfToken || !email.trim() ? "disabled" : ""}`}
          >
            {busy ? "Analysis in progress…" : "Choose a PDF"}
            <input
              type="file"
              accept="application/pdf,.pdf"
              disabled={busy || !csrfToken || !email.trim()}
              onChange={(event) => {
                void analyze(event.currentTarget.files?.[0]);
                event.currentTarget.value = "";
              }}
            />
          </label>
          {error && (
            <p className="alert" role="alert">
              {error}
            </p>
          )}
        </section>
        <p className="guest-limit-note">
          Guest access includes one analysis per session. Create an account to
          keep reports in your history.
        </p>
      </main>
    </div>
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
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [documentToDelete, setDocumentToDelete] = useState<Document | null>(
    null,
  );
  const [message, setMessage] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [activeJobs, setActiveJobs] = useState<
    { job_id: string; filename: string }[]
  >([]);
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
    let hadJobs = false;
    const refreshJobs = async () => {
      try {
        const result = await request<{
          jobs: { job_id: string; filename: string }[];
        }>("/jobs");
        if (!active) return;
        setActiveJobs(result.jobs);
        if (hadJobs && result.jobs.length === 0) await load();
        hadJobs = result.jobs.length > 0;
      } catch {
        // The document list remains usable if the status refresh is unavailable.
      }
    };
    void refreshJobs();
    const interval = window.setInterval(() => void refreshJobs(), 3000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [load]);

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
      await request<{ filename: string; job_id: string }>("/jobs", {
        method: "POST",
        headers: { "X-CSRF-Token": csrf.csrf_token },
        body,
      });
      void load();
    } catch (cause) {
      setUploadError(cause instanceof Error ? cause.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function deleteAnalysis(document: Document) {
    setUploadError("");
    setMessage("");
    setDeletingId(document.id);
    try {
      const csrf = await request<{ csrf_token: string }>("/csrf");
      await request(`/documents/${document.id}`, {
        method: "DELETE",
        headers: { "X-CSRF-Token": csrf.csrf_token },
      });
      setMessage(`Deleted ${document.filename}.`);
      await load();
    } catch (cause) {
      setUploadError(
        cause instanceof Error ? cause.message : "Could not delete analysis.",
      );
    } finally {
      setDeletingId(null);
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
        {activeJobs.length > 0 && (
          <section className="job-list" aria-live="polite">
            {activeJobs.map((job) => (
              <p key={job.job_id}>
                Analysis in progress: <strong>{job.filename}</strong>.
              </p>
            ))}
          </section>
        )}
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
                <div className="document-row" key={doc.id}>
                  <Link
                    className="document-row-open"
                    to={`/documents/${doc.id}`}
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
                  <button
                    className="delete-button"
                    type="button"
                    disabled={deletingId === doc.id}
                    aria-label={`Delete ${doc.filename}`}
                    onClick={() => setDocumentToDelete(doc)}
                  >
                    {deletingId === doc.id ? "Deleting…" : "Delete"}
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
      {documentToDelete && (
        <div className="confirm-overlay">
          <section
            className="confirm-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-dialog-title"
            aria-describedby="delete-dialog-description"
          >
            <p className="eyebrow">REMOVE REPORT</p>
            <h2 id="delete-dialog-title">Delete this analysis?</h2>
            <p id="delete-dialog-description">
              “{documentToDelete.filename}” and its report will be permanently
              deleted.
            </p>
            <div className="confirm-actions">
              <button
                className="quiet-button"
                type="button"
                onClick={() => setDocumentToDelete(null)}
              >
                Cancel
              </button>
              <button
                className="delete-confirm-button"
                type="button"
                disabled={deletingId === documentToDelete.id}
                onClick={() => {
                  const document = documentToDelete;
                  setDocumentToDelete(null);
                  void deleteAnalysis(document);
                }}
              >
                Delete report
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

function ResultsPage({ guest = false }: { guest?: boolean }) {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const accessToken = searchParams.get("access") || "";
  const [data, setData] = useState<AnalysisReport | null>(null);
  const [error, setError] = useState("");
  const [jobStatus, setJobStatus] = useState("");
  const [resultFilter, setResultFilter] = useState<ResultsFilter[]>(["all"]);
  const [showStatusHelp, setShowStatusHelp] = useState(false);
  const [copiedReferenceId, setCopiedReferenceId] = useState<number | null>(
    null,
  );

  const copyReferenceSearchText = async (item: Finding) => {
    const title = item.title?.trim();
    const authors = item.authors?.trim();
    const year = item.year ? String(item.year) : "";
    const doi = item.doi?.trim();

    const parts = [title, authors, year, doi ? `DOI: ${doi}` : null].filter(
      Boolean,
    ) as string[];

    const value = parts.length ? parts.join(". ") : "";
    if (!value) return;

    try {
      await navigator.clipboard.writeText(value);
      setCopiedReferenceId(item.reference_id);
      window.setTimeout(() => {
        setCopiedReferenceId((current) =>
          current === item.reference_id ? null : current,
        );
      }, 1200);
    } catch {
      // no-op: clipboard access is optional for this quick helper
    }
  };

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        if (guest) {
          const query = accessToken
            ? `?access=${encodeURIComponent(accessToken)}`
            : "";
          const result = await request<{
            status: string;
            report?: AnalysisReport;
            error_code?: string;
          }>(`/guest/reports/${id}${query}`);
          if (!alive) return;
          setJobStatus(result.status);
          if (result.status === "completed" && result.report)
            setData(result.report);
          else if (result.status === "failed")
            setError(
              result.error_code === "NO_REFERENCES_FOUND"
                ? "No references were found in this PDF."
                : "The analysis could not be completed. Check your email for an update.",
            );
        } else {
          const result = await request<AnalysisReport>(
            `/documents/${id}/results`,
          );
          if (alive) setData(result);
        }
      } catch (cause) {
        if (alive)
          setError(
            cause instanceof Error ? cause.message : "Could not load results.",
          );
      }
    };
    void load();
    const interval = guest
      ? window.setInterval(() => void load(), 3000)
      : undefined;
    return () => {
      alive = false;
      if (interval) window.clearInterval(interval);
    };
  }, [guest, id, accessToken]);
  if (error)
    return (
      <div className="app-shell">
        <header className="topbar">
          <Brand />
        </header>
        <main className="dashboard">
          <Link to="/" className="back-link">
            {guest ? "← Back to Retraction Checker" : "← Back to documents"}
          </Link>
          <p className="alert">{error}</p>
        </main>
      </div>
    );
  if (!data)
    return (
      <main className="center-screen">
        <p>
          {jobStatus === "running"
            ? "Analysis is running. This page will update when it is ready."
            : "Your report is queued. This page will update when it is ready."}
        </p>
      </main>
    );
  const filterOptions: Array<{ value: ResultsFilter; label: string }> = [
    { value: "all", label: "All references" },
    { value: "retracted", label: "Retracted" },
    { value: "verified", label: "Verified" },
    { value: "missing_doi", label: "Missing DOI" },
    { value: "not_verified", label: "No retraction notice found" },
  ];

  const findings = filterFindings(data.results, resultFilter);
  return (
    <div className="app-shell">
      <header className="topbar">
        <Brand />
      </header>
      <main className="dashboard">
        <Link to="/" className="back-link">
          {guest ? "← Retraction Checker" : "← All documents"}
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
        </div>
        <div className="filter-panel">
          <div className="filter-header-row">
            <div className="filter-options">
              {filterOptions.map((option) => {
                const checked = resultFilter.includes(option.value);
                return (
                  <label key={option.value} className="filter-option">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => {
                        setResultFilter((current) => {
                          if (option.value === "all") {
                            return ["all"];
                          }
                          const next = current.filter((item) => item !== "all");
                          if (next.includes(option.value)) {
                            const removed = next.filter(
                              (item) => item !== option.value,
                            );
                            return removed.length ? removed : ["all"];
                          }
                          return [...next, option.value];
                        });
                      }}
                    />
                    <span>{option.label}</span>
                  </label>
                );
              })}
            </div>
            <button
              type="button"
              className="status-help-button"
              aria-label="Help with status meanings"
              aria-expanded={showStatusHelp}
              onClick={() => setShowStatusHelp((current) => !current)}
            >
              ?
            </button>
          </div>
          {showStatusHelp ? (
            <div
              className="status-help-popover"
              role="dialog"
              aria-live="polite"
            >
              <ul>
                <li>
                  <strong>Retracted</strong> — the reference is listed as
                  retracted in Retraction Watch.
                </li>
                <li>
                  <strong>Verified</strong> — the reference matches a record in
                  Retraction Watch and appears safe.
                </li>
                <li>
                  <strong>Missing DOI</strong> — the citation did not include a
                  DOI, so it could not be checked automatically.
                </li>
                <li>
                  <strong>No retraction notice found</strong> — no active
                  retraction warning was found, but this should still be checked
                  manually if the citation or DOI looks uncertain.
                </li>
              </ul>
            </div>
          ) : null}
          {resultFilter.includes("all") ? null : (
            <div className="active-filter-row" aria-label="Active filters">
              {resultFilter.map((filter) => {
                const label =
                  filter === "retracted"
                    ? "Retracted"
                    : filter === "verified"
                      ? "Verified"
                      : filter === "missing_doi"
                        ? "Missing DOI"
                        : "No retraction notice found";
                return (
                  <button
                    key={filter}
                    type="button"
                    className="filter-chip"
                    onClick={() => {
                      setResultFilter((current) => {
                        const next = current.filter((item) => item !== filter);
                        return next.length ? next : ["all"];
                      });
                    }}
                    aria-label={`Remove ${label} filter`}
                  >
                    {label}
                    <span aria-hidden="true">×</span>
                  </button>
                );
              })}
            </div>
          )}
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
                <div className="finding-status-stack">
                  <span
                    className={`result-badge ${verificationClass(item.verification_status)}`}
                  >
                    {verificationLabel(item.verification_status)}
                  </span>
                  {(item.title || item.authors || item.year || item.doi) && (
                    <button
                      type="button"
                      className="copy-search-button"
                      onClick={() => void copyReferenceSearchText(item)}
                    >
                      {copiedReferenceId === item.reference_id
                        ? "Copied"
                        : "Copy citation"}
                    </button>
                  )}
                </div>
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
              {(item.verification_note ||
                verificationInfo(item.verification_status)) && (
                <p className="verification-note">
                  {item.verification_note ||
                    verificationInfo(item.verification_status)}
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
