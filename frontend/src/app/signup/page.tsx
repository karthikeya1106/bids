"use client";
import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Zap, Loader, ShieldCheck, ArrowRight } from "lucide-react";
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

export default function SignupPage() {
  const { status } = useSession();
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  // After creating the account we send the user to the uploader; without this
  // guard the session effect below races it and lands them on the launchpad.
  const navigatingAfterSignup = useRef(false);

  useEffect(() => {
    if (status === "authenticated" && !navigatingAfterSignup.current) {
      router.replace("/home");
    }
  }, [status, router]);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (loading) return;
    setError("");

    if (password.length < 8) {
      setError("Choose a password with at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), email: email.trim(), password }),
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        setError(payload?.detail || "Could not create the account.");
        return;
      }

      const result = await signIn("credentials", {
        email: email.trim(),
        password,
        redirect: false,
      });
      if (!result || result.error) {
        setError("Account created, but sign-in failed. Please sign in manually.");
        return;
      }
      navigatingAfterSignup.current = true;
      router.replace("/upload");
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

        <div className="auth-heading">Create your workspace.</div>
        <div className="auth-subheading">
          Every account gets a private workspace. Nothing is preloaded — upload your own dataset to activate the modules.
        </div>

        <form onSubmit={handleSubmit} noValidate style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 6 }}>
          <div>
            <label htmlFor="signup-name" style={labelStyle}>Name</label>
            <input
              id="signup-name"
              type="text"
              autoComplete="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Jane Analyst"
              style={inputStyle}
            />
          </div>
          <div>
            <label htmlFor="signup-email" style={labelStyle}>Work email</label>
            <input
              id="signup-email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              style={inputStyle}
            />
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            <div>
              <label htmlFor="signup-password" style={labelStyle}>Password</label>
              <input
                id="signup-password"
                type="password"
                autoComplete="new-password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="8+ characters"
                style={inputStyle}
              />
            </div>
            <div>
              <label htmlFor="signup-confirm" style={labelStyle}>Confirm</label>
              <input
                id="signup-confirm"
                type="password"
                autoComplete="new-password"
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                placeholder="Repeat password"
                style={inputStyle}
              />
            </div>
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
            disabled={loading || !email || !password || !confirm}
            id="create-account-btn"
          >
            {loading ? (
              <Loader size={18} color="#ffffff" style={{ animation: "spin 1s linear infinite" }} />
            ) : (
              <span style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "center", width: "100%" }}>
                Create account <ArrowRight size={16} />
              </span>
            )}
          </button>
        </form>

        <div
          style={{
            display: "flex", alignItems: "center", gap: 8,
            marginTop: 18, padding: "10px 14px",
            background: "#f9fafb", border: "1px solid var(--border)", borderRadius: 10,
          }}
        >
          <ShieldCheck size={16} color="#111111" />
          <span style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>
            Passwords are hashed, and data is scoped to your account only.
          </span>
        </div>

        <div className="auth-footer-text">
          Already have an account?{" "}
          <Link href="/login" className="auth-footer-link">Sign in</Link>
        </div>
      </div>
    </div>
  );
}
