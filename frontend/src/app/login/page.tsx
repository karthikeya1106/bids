"use client";
import { signIn, useSession, getProviders } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Zap, Loader, ArrowRight, ShieldCheck } from "lucide-react";
import Link from "next/link";

const inputStyle: React.CSSProperties = {
  width: "100%",
  background: "#ffffff",
  border: "1px solid var(--border)",
  borderRadius: 10,
  color: "var(--text-primary)",
  fontSize: 13.5,
  padding: "11px 14px",
  fontFamily: "inherit",
  outline: "none",
  boxSizing: "border-box",
};

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 11.5,
  fontWeight: 700,
  color: "var(--text-secondary)",
  marginBottom: 6,
  textTransform: "uppercase",
  letterSpacing: "0.05em",
};

export default function LoginPage() {
  const { status } = useSession();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [googleEnabled, setGoogleEnabled] = useState(false);

  useEffect(() => {
    if (status === "authenticated") router.replace("/home");
  }, [status, router]);

  useEffect(() => {
    getProviders()
      .then((providers) => setGoogleEnabled(Boolean(providers?.google)))
      .catch(() => setGoogleEnabled(false));
  }, []);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (loading) return;
    setError("");
    setLoading(true);
    try {
      const result = await signIn("credentials", {
        email: email.trim(),
        password,
        redirect: false,
      });
      if (!result || result.error) {
        setError("Email or password is incorrect.");
        return;
      }
      router.replace("/home");
      router.refresh();
    } catch {
      setError("Could not reach the server. Check that both services are running.");
    } finally {
      setLoading(false);
    }
  };

  if (status === "loading") {
    return (
      <div className="auth-page">
        <Loader size={24} color="#000000" style={{ animation: "spin 1s linear infinite" }} />
      </div>
    );
  }

  return (
    <div className="auth-page">
      <Link
        href="/"
        style={{
          position: "absolute", top: 24, left: 24, zIndex: 20,
          fontSize: 12, fontWeight: 600, color: "var(--text-secondary)",
          textDecoration: "none",
        }}
      >
        ← Back to home
      </Link>
      <div className="auth-card">
        <div className="auth-logo">
          <div className="auth-logo-icon">
            <Zap size={20} color="#ffffff" strokeWidth={2.5} />
          </div>
          <div>
            <div className="auth-logo-title">BIDS</div>
            <div className="auth-logo-sub">Intelligence Platform</div>
          </div>
        </div>

        <div className="auth-heading">Welcome back.</div>
        <div className="auth-subheading">
          Sign in to your own workspace. Your datasets, KPIs and reports are private to your account.
        </div>

        <form onSubmit={handleSubmit} noValidate style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 6 }}>
          <div>
            <label htmlFor="login-email" style={labelStyle}>Email</label>
            <input
              id="login-email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              style={inputStyle}
            />
          </div>
          <div>
            <label htmlFor="login-password" style={labelStyle}>Password</label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Your password"
              style={inputStyle}
            />
          </div>

          {error && (
            <div
              role="alert"
              style={{
                fontSize: 12.5, color: "#b91c1c", background: "#fef2f2",
                border: "1px solid #fecaca", borderRadius: 8, padding: "9px 12px",
              }}
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            className="auth-google-btn"
            disabled={loading || !email || !password}
            id="credentials-signin-btn"
          >
            {loading ? (
              <Loader size={18} color="#ffffff" style={{ animation: "spin 1s linear infinite" }} />
            ) : (
              <span style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "center", width: "100%" }}>
                Sign in <ArrowRight size={16} />
              </span>
            )}
          </button>
        </form>

        {googleEnabled && (
          <>
            <div className="auth-divider">
              <div className="auth-divider-line" />
              <span className="auth-divider-text">or</span>
              <div className="auth-divider-line" />
            </div>
            <button
              className="btn-ghost"
              style={{
                width: "100%", padding: "12px 16px", justifyContent: "center",
                fontSize: 13.5, fontWeight: 600, borderRadius: 10,
              }}
              onClick={() => signIn("google", { callbackUrl: "/home" })}
              disabled={loading}
              id="google-signin-btn"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
                <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
                <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
                <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
              </svg>
              Continue with Google
            </button>
          </>
        )}

        <div
          style={{
            display: "flex", alignItems: "center", gap: 8,
            marginTop: 18, padding: "10px 14px",
            background: "#f9fafb", border: "1px solid var(--border)", borderRadius: 10,
          }}
        >
          <ShieldCheck size={16} color="#111111" />
          <span style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>
            Workspaces are isolated — nobody can read another account&apos;s data.
          </span>
        </div>

        <div className="auth-footer-text">
          Don&apos;t have an account?{" "}
          <Link href="/signup" className="auth-footer-link">Create account</Link>
        </div>
      </div>
    </div>
  );
}
