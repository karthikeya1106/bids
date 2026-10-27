"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowRight, Loader, Lock, ShieldCheck, Upload } from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import TopBar from "@/components/layout/TopBar";
import { getUploadStatus } from "@/lib/api";

// Pages that provide their own chrome (marketing landing, auth screens).
const STANDALONE_ROUTES = ["/", "/login", "/signup"];

// Analytics modules only make sense once this account has uploaded a dataset.
// Each route maps to the backend's capability key so a churn or generic dataset
// does not open pages that would show sales metrics it cannot support.
const MODULE_ROUTES: Record<string, string> = {
  "/dashboard": "dashboard",
  "/behavior": "behavior",
  "/segmentation": "segmentation",
  "/rootcause": "rootcause",
  "/drift": "drift",
  "/forecasting": "forecast",
  "/analysis": "analysis",
};

function WorkspaceUnavailable({ schemaLabel }: { schemaLabel: string }) {
  return (
    <div className="panel panel-body animate-fade-up" style={{ textAlign: "center", padding: "68px 28px", maxWidth: 620, margin: "48px auto" }}>
      <div style={{
        width: 56, height: 56, borderRadius: 16, background: "#f3f4f6",
        border: "1px solid var(--border)", display: "flex", alignItems: "center",
        justifyContent: "center", margin: "0 auto 18px",
      }}>
        <ShieldCheck size={22} color="#111111" />
      </div>
      <div style={{ fontSize: 19, fontWeight: 800, letterSpacing: -0.3, marginBottom: 8 }}>
        Not supported by this dataset
      </div>
      <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6, maxWidth: 440, margin: "0 auto 22px" }}>
        The active dataset is classified as <strong>{schemaLabel}</strong>. This module needs
        sales transaction history, so it would only show empty or misleading figures.
        The Analysis Report explains what this dataset actually supports.
      </p>
      <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
        <Link href="/analysis" className="btn-primary" style={{ textDecoration: "none" }}>
          <ArrowRight size={14} /> Open Analysis Report
        </Link>
        <Link href="/upload" className="btn-ghost" style={{ textDecoration: "none" }}>
          <Upload size={14} /> Upload another dataset
        </Link>
      </div>
    </div>
  );
}

function WorkspaceEmpty() {
  return (
    <div className="panel panel-body animate-fade-up" style={{ textAlign: "center", padding: "72px 28px", maxWidth: 620, margin: "48px auto" }}>
      <div style={{
        width: 56, height: 56, borderRadius: 16, background: "#f3f4f6",
        border: "1px solid var(--border)", display: "flex", alignItems: "center",
        justifyContent: "center", margin: "0 auto 18px",
      }}>
        <Lock size={22} color="#111111" />
      </div>
      <div style={{ fontSize: 19, fontWeight: 800, letterSpacing: -0.3, marginBottom: 8 }}>
        This module is locked
      </div>
      <p style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.6, maxWidth: 420, margin: "0 auto 22px" }}>
        Your workspace has no dataset yet. Upload a CSV or Excel export to unlock every module —
        nothing is preloaded, and the data you upload is visible only to your account.
      </p>
      <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
        <Link href="/upload" className="btn-primary" style={{ textDecoration: "none" }}>
          <Upload size={14} /> Upload data
        </Link>
        <Link href="/home" className="btn-ghost" style={{ textDecoration: "none" }}>
          <ArrowRight size={14} /> Back to launchpad
        </Link>
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 7, marginTop: 24, fontSize: 11.5, color: "var(--text-muted)" }}>
        <ShieldCheck size={13} /> Every workspace is isolated by account.
      </div>
    </div>
  );
}

function WorkspaceLoading() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12, padding: "96px 0", color: "var(--text-muted)" }}>
      <Loader size={20} style={{ animation: "spin 1s linear infinite" }} />
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>Checking workspace…</span>
    </div>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isStandalone = STANDALONE_ROUTES.includes(pathname);
  const route = Object.keys(MODULE_ROUTES).find(
    (candidate) => pathname === candidate || pathname.startsWith(`${candidate}/`),
  );
  const needsData = Boolean(route);
  // Keyed by path so a previous route's answer can never authorise the next one.
  const [probe, setProbe] = useState<{
    path: string;
    hasData: boolean;
    modules: Record<string, boolean>;
    schemaLabel: string;
  } | null>(null);

  useEffect(() => {
    if (!needsData) return;
    let cancelled = false;

    getUploadStatus()
      .then((status) => {
        if (!cancelled) {
          setProbe({
            path: pathname,
            hasData: Boolean(status?.has_data),
            modules: (status?.modules as Record<string, boolean>) || {},
            schemaLabel: (status?.schema_label as string) || "another dataset type",
          });
        }
      })
      .catch(() => {
        // Let the module render its own error state if the API is unreachable.
        if (!cancelled) setProbe({ path: pathname, hasData: true, modules: {}, schemaLabel: "" });
      });

    return () => { cancelled = true; };
  }, [pathname, needsData]);

  if (isStandalone) {
    return <>{children}</>;
  }

  const hasData = probe?.path === pathname ? probe.hasData : null;
  const blocked = needsData && hasData === false;
  const checking = needsData && hasData === null;
  const moduleKey = route ? MODULE_ROUTES[route] : undefined;
  const supported = moduleKey && probe ? probe.modules[moduleKey] !== false : true;
  // The Analysis Report always works; it adapts to the dataset it is given.
  const unavailable = needsData && hasData === true && !supported;

  return (
    <div className="app-shell">
      <Sidebar />
      <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
        <TopBar />
        <main className="main-content">
          {blocked ? <WorkspaceEmpty />
            : checking ? <WorkspaceLoading />
            : unavailable ? <WorkspaceUnavailable schemaLabel={probe?.schemaLabel || "another dataset type"} />
            : children}
        </main>
      </div>
    </div>
  );
}
