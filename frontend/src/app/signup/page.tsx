"use client";
import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Zap, Loader, ShieldCheck, ArrowRight } from "lucide-react";
import Link from "next/link";

export default function SignupPage() {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/dashboard");
    }
  }, [status, router]);

  const handleGoogleSignUp = async () => {
    setLoading(true);
    try {
      await signIn("google", { callbackUrl: "/dashboard" });
    } finally {
      setLoading(false);
    }
  };

  const handleDemoSignIn = async () => {
    setLoading(true);
    try {
      await signIn("credentials", {
        email: "demo.executive@bids.ai",
        password: "demo",
        callbackUrl: "/dashboard",
      });
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
      <div className="auth-card">
        {/* Logo */}
        <div className="auth-logo">
          <div className="auth-logo-icon">
            <Zap size={20} color="#ffffff" strokeWidth={2.5} />
          </div>
          <div>
            <div className="auth-logo-title">BIDS</div>
            <div className="auth-logo-sub">Intelligence Platform</div>
          </div>
        </div>

        {/* Heading */}
        <div className="auth-heading">Create account.</div>
        <div className="auth-subheading">
          Get instant access to BIDS — the enterprise analytics platform powered by XGBoost forecasting and Gemini AI.
        </div>

        {/* Demo Fast Access */}
        <button
          className="auth-google-btn"
          onClick={handleDemoSignIn}
          disabled={loading}
          style={{ marginBottom: 12 }}
          id="demo-signup-btn"
        >
          {loading ? (
            <Loader size={18} color="#ffffff" style={{ animation: "spin 1s linear infinite" }} />
          ) : (
            <div style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "center", width: "100%" }}>
              <span>Instant Workspace Access</span>
              <ArrowRight size={16} />
            </div>
          )}
        </button>

        {/* Google Sign-Up Button */}
        <button
          className="btn-ghost"
          style={{
            width: "100%", padding: "12px 16px", justifyContent: "center",
            fontSize: 13.5, fontWeight: 600, borderRadius: 10,
          }}
          onClick={handleGoogleSignUp}
          disabled={loading}
          id="google-signup-btn"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
          </svg>
          Sign up with Google
        </button>

        {/* Trust badge */}
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "10px 14px",
          background: "#f9fafb",
          border: "1px solid var(--border)",
          borderRadius: 10,
          marginTop: 18,
        }}>
          <ShieldCheck size={16} color="#111111" />
          <span style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>
            Secured by Google OAuth 2.0. No passwords stored.
          </span>
        </div>

        {/* What you get */}
        <div style={{ marginTop: 22, marginBottom: 4 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 12 }}>
            What you get
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            {[
              "Executive Dashboard",
              "Behavior Analytics",
              "Customer Segmentation",
              "Root Cause Analysis",
              "Data Drift & BPR",
              "Forecast & Strategy AI",
            ].map((f, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{
                  width: 5, height: 5, borderRadius: "50%",
                  background: "#111111", flexShrink: 0,
                }} />
                <span style={{ fontSize: 11.5, color: "var(--text-secondary)" }}>{f}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <div className="auth-footer-text">
          Already have an account?{" "}
          <Link href="/login" className="auth-footer-link">
            Sign in
          </Link>
        </div>
      </div>
    </div>
  );
}
