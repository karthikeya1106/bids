"use client";
import { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { useSession } from "next-auth/react";
import {
  Activity, AlertTriangle, ArrowRight, BarChart3, CheckCircle2,
  Database, FileBarChart2, Home, LayoutDashboard, Layers, PieChart,
  Search, ShieldCheck, Sparkles, TrendingUp, Upload, Zap,
  Cpu, ArrowUpRight, Clock,
} from "lucide-react";
import { getUploadStatus, getHealthScore } from "@/lib/api";
import { formatCurrency, formatNumber } from "@/lib/format";

interface ModuleCardDef {
  id: string;
  name: string;
  category: "Executive" | "Customer" | "Diagnostics" | "Predictive" | "Data";
  categoryLabel: string;
  href: string;
  icon: any;
  tag: string;
  tagType: "success" | "info" | "warning" | "neutral";
  summary: string;
  features: string[];
  metricsPreview?: string;
  badge?: string;
}

const MODULES: ModuleCardDef[] = [
  {
    id: "dashboard",
    name: "Executive Dashboard",
    category: "Executive",
    categoryLabel: "Executive Suite",
    href: "/dashboard",
    icon: LayoutDashboard,
    tag: "Core Telemetry",
    tagType: "neutral",
    summary: "High-level command center with trailing revenue, profit margins, AOV, and instant data-driven anomalies.",
    features: ["Revenue & profit deltas", "Monthly category mix", "Data-derived executive alerts"],
    metricsPreview: "Trailing KPIs · Alerts",
  },
  {
    id: "behavior",
    name: "Behavior Analytics",
    category: "Customer",
    categoryLabel: "Customer Intelligence",
    href: "/behavior",
    icon: Activity,
    tag: "Cohort Analysis",
    tagType: "info",
    summary: "Cohort retention dynamics, purchase lifecycle progression, and discount price elasticity curves.",
    features: ["Quarterly retention matrix", "Lifecycle conversion funnel", "Discount margin impact"],
    metricsPreview: "Cohorts · Funnel · Discounts",
  },
  {
    id: "segmentation",
    name: "Customer Segments",
    category: "Customer",
    categoryLabel: "Customer Intelligence",
    href: "/segmentation",
    icon: PieChart,
    tag: "K-Means + RFM",
    tagType: "success",
    summary: "Machine learning customer clustering dividing your audience into Champions, At-Risk, and Growing tiers.",
    features: ["RFM quintile scoring", "Segment revenue share", "Top individual account profiles"],
    metricsPreview: "4 Business Clusters",
  },
  {
    id: "rootcause",
    name: "Root Cause Analysis",
    category: "Diagnostics",
    categoryLabel: "Diagnostics",
    href: "/rootcause",
    icon: AlertTriangle,
    tag: "Ishikawa Anomaly",
    tagType: "warning",
    summary: "Statistical outlier detection across monthly revenue explained through a weighted multi-branch causal fishbone.",
    features: ["Z-Score anomaly detection", "Six scored causal branches", "Evidence-backed drivers"],
    metricsPreview: "Fishbone Diagram · Drivers",
  },
  {
    id: "drift",
    name: "Data Drift & BPR",
    category: "Diagnostics",
    categoryLabel: "Governance & ML",
    href: "/drift",
    icon: BarChart3,
    tag: "ADWIN Change Points",
    tagType: "info",
    summary: "Continuous streaming drift detection on operational KPIs, PSI population shifts, and audited business process rules.",
    features: ["ADWIN stream change detection", "PSI feature mix drift", "BPR rule effectiveness scoring"],
    metricsPreview: "ADWIN Points · PSI Scores",
  },
  {
    id: "forecasting",
    name: "Forecast & Strategy",
    category: "Predictive",
    categoryLabel: "Predictive & AI",
    href: "/forecasting",
    icon: TrendingUp,
    tag: "XGBoost Engine",
    tagType: "success",
    summary: "Six-month machine learning revenue forecasting, interactive price/discount elasticity sliders, and AI strategy plays.",
    features: ["6-Month horizon forecast", "Interactive what-if simulations", "Actionable executive playbooks"],
    metricsPreview: "6-Mo Forecast · What-If",
  },
  {
    id: "analysis",
    name: "Analysis Report",
    category: "Executive",
    categoryLabel: "Intelligence",
    href: "/analysis",
    icon: FileBarChart2,
    tag: "Comprehensive Brief",
    tagType: "neutral",
    summary: "Consolidated enterprise intelligence audit with overall business health scoring and prioritized action recommendations.",
    features: ["Algorithmic business health score", "Cross-metric benchmarks", "Prioritized strategic initiatives"],
    metricsPreview: "Health Score · Action Plan",
  },
  {
    id: "upload",
    name: "Data Ingestion & Auto-Mapping",
    category: "Data",
    categoryLabel: "Data Pipeline",
    href: "/upload",
    icon: Upload,
    tag: "16-Field Schema",
    tagType: "info",
    summary: "Drag-and-drop raw sales or customer CSV/Excel datasets with intelligent column auto-mapping and instant synthesis.",
    features: ["16-Field fuzzy alias mapping", "Automatic synthesis fallback", "Instant model re-indexing"],
    metricsPreview: "Self-Serve Ingestion",
  },
];

const CATEGORIES = [
  { id: "all", label: "All Modules" },
  { id: "Executive", label: "Executive & Reports" },
  { id: "Customer", label: "Customer & Cohorts" },
  { id: "Diagnostics", label: "Diagnostics & Drift" },
  { id: "Predictive", label: "Predictive & AI" },
  { id: "Data", label: "Data Pipeline" },
];

export default function HomePage() {
  const { data: session } = useSession();
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [status, setStatus] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([getUploadStatus(), getHealthScore()]).then(([statusRes, healthRes]) => {
      if (cancelled) return;
      if (statusRes.status === "fulfilled") setStatus(statusRes.value);
      if (healthRes.status === "fulfilled") setHealth(healthRes.value);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, []);

  const filteredModules = useMemo(() => {
    return MODULES.filter((mod) => {
      const matchesCategory =
        selectedCategory === "all" || mod.category === selectedCategory;
      const q = searchQuery.toLowerCase().trim();
      const matchesSearch =
        !q ||
        mod.name.toLowerCase().includes(q) ||
        mod.summary.toLowerCase().includes(q) ||
        mod.features.some((f) => f.toLowerCase().includes(q)) ||
        mod.categoryLabel.toLowerCase().includes(q);
      return matchesCategory && matchesSearch;
    });
  }, [selectedCategory, searchQuery]);

  const firstName = session?.user?.name ? session.user.name.split(" ")[0] : "Executive";

  return (
    <div style={{ maxWidth: 1240, margin: "0 auto", paddingBottom: 48 }}>
      {/* ── Top Hero / Greeting Section ── */}
      <div
        className="animate-fade-up"
        style={{
          background: "#ffffff",
          border: "1px solid var(--border)",
          borderRadius: 16,
          padding: "24px 28px",
          marginBottom: 20,
          boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 20, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 280 }}>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 10px", borderRadius: 20, background: "#f3f4f6", fontSize: 11, fontWeight: 700, color: "var(--text-secondary)", marginBottom: 10 }}>
              <Sparkles size={13} color="#111111" />
              <span>BIDS Intelligence Suite</span>
              <span style={{ color: "#d1d5db" }}>•</span>
              <span style={{ color: "#047857" }}>All Systems Active</span>
            </div>
            <h1 style={{ fontSize: 24, fontWeight: 800, letterSpacing: "-0.02em", color: "#111111", marginBottom: 6 }}>
              Welcome back, {firstName}
            </h1>
            <p style={{ fontSize: 13, color: "var(--text-secondary)", maxWidth: 620, lineHeight: 1.5 }}>
              Select a module from the launchpad below to inspect executive telemetry, drill into customer behavior, run predictive models, or ingest new data.
            </p>
          </div>

          {/* Quick Telemetry Pills */}
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <div style={{
              background: "#f9fafb", border: "1px solid var(--border)",
              borderRadius: 12, padding: "10px 14px", minWidth: 130,
            }}>
              <div style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: 2 }}>
                Active Dataset
              </div>
              <div style={{ fontSize: 13, fontWeight: 800, color: "#111111", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 140 }}>
                {status?.has_data ? (status.dataset_name || "Uploaded dataset") : "Not connected"}
              </div>
              <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>
                {status?.has_data ? (status.org_name || "Active workspace") : "Upload to activate"}
              </div>
            </div>

            <div style={{
              background: "#f9fafb", border: "1px solid var(--border)",
              borderRadius: 12, padding: "10px 14px", minWidth: 120,
            }}>
              <div style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: 2 }}>
                Total Records
              </div>
              <div style={{ fontSize: 13, fontWeight: 800, color: "#111111" }}>
                {status?.order_count ? formatNumber(status.order_count) : "—"}
              </div>
              <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>
                {status?.customer_count ? `${status.customer_count} Customers` : "Synchronized"}
              </div>
            </div>

            <div style={{
              background: "#f9fafb", border: "1px solid var(--border)",
              borderRadius: 12, padding: "10px 14px", minWidth: 120,
            }}>
              <div style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: 2 }}>
                Health Score
              </div>
              <div style={{ fontSize: 13, fontWeight: 800, color: "#047857", display: "flex", alignItems: "center", gap: 4 }}>
                <CheckCircle2 size={13} color={health?.score ? "#047857" : "#9ca3af"} />
                {health?.score ? `${health.score.toFixed(0)} / 100` : "—"}
              </div>
              <div style={{ fontSize: 10.5, color: "var(--text-muted)" }}>
                {health?.status ?? "No dataset"}
              </div>
            </div>
          </div>
        </div>

        {/* ── Search & Filter Controls ── */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          gap: 12, marginTop: 20, paddingTop: 18, borderTop: "1px solid var(--border-subtle)",
          flexWrap: "wrap",
        }}>
          {/* Category Tabs */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {CATEGORIES.map((cat) => (
              <button
                key={cat.id}
                onClick={() => setSelectedCategory(cat.id)}
                className={selectedCategory === cat.id ? "btn-primary" : "btn-ghost"}
                style={{
                  padding: "5px 12px",
                  fontSize: 11.5,
                  borderRadius: 20,
                  transition: "all 0.15s ease",
                }}
              >
                {cat.label}
              </button>
            ))}
          </div>

          {/* Search Box */}
          <div style={{ position: "relative", minWidth: 240, flex: "0 1 280px" }}>
            <Search size={14} color="#9ca3af" style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)" }} />
            <input
              type="text"
              placeholder="Filter modules or capabilities…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: "100%",
                padding: "6px 12px 6px 32px",
                fontSize: 12,
                borderRadius: 20,
                border: "1px solid var(--border)",
                background: "#f9fafb",
                outline: "none",
              }}
            />
          </div>
        </div>
      </div>

      {/* ── Empty workspace call to action ── */}
      {!loading && status && !status.has_data && (
        <div
          className="panel panel-body animate-fade-up"
          style={{
            marginBottom: 18, opacity: 0,
            display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap",
            borderLeft: "4px solid #000000",
          }}
        >
          <div style={{
            width: 42, height: 42, borderRadius: 12, flexShrink: 0,
            background: "#000000", color: "#ffffff",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <Database size={19} />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <div style={{ fontSize: 13.5, fontWeight: 800, color: "#111111", marginBottom: 3 }}>
              Your workspace is empty
            </div>
            <p style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.55 }}>
              Upload a dataset to unlock every module. Nothing is shown until you do, and only you can see what you upload.
            </p>
          </div>
          <Link href="/upload" className="btn-primary" style={{ textDecoration: "none", fontSize: 12.5 }}>
            <Upload size={14} /> Upload dataset
          </Link>
          <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--text-muted)" }}>
            <ShieldCheck size={13} /> Private to your account
          </div>
        </div>
      )}

      {/* ── Section Title ── */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14, padding: "0 4px" }}>
        <div style={{ fontSize: 14, fontWeight: 800, color: "#111111", letterSpacing: "-0.01em" }}>
          Platform Modules ({filteredModules.length})
        </div>
        <div style={{ fontSize: 11.5, color: "var(--text-muted)" }}>
          Click any card to launch workspace
        </div>
      </div>

      {/* ── Module Grid (Matching User Wireframe 3-column Layout) ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
          gap: 16,
        }}
      >
        {filteredModules.map((module, index) => {
          const Icon = module.icon;
          return (
            <Link
              key={module.id}
              href={module.href}
              style={{ textDecoration: "none", color: "inherit", display: "block" }}
              className="animate-fade-up"
            >
              <div
                style={{
                  background: "#ffffff",
                  border: "1px solid var(--border)",
                  borderRadius: 14,
                  padding: "20px 22px",
                  height: "100%",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  transition: "all 0.2s cubic-bezier(0.16, 1, 0.3, 1)",
                  cursor: "pointer",
                  position: "relative",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.02)",
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = "#111111";
                  e.currentTarget.style.transform = "translateY(-3px)";
                  e.currentTarget.style.boxShadow = "0 8px 24px rgba(0,0,0,0.07)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = "var(--border)";
                  e.currentTarget.style.transform = "translateY(0px)";
                  e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.02)";
                }}
              >
                <div>
                  {/* Card Header: Icon + Category + Status */}
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                      <div
                        style={{
                          width: 40,
                          height: 40,
                          borderRadius: 10,
                          background: "#111111",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          color: "#ffffff",
                          flexShrink: 0,
                        }}
                      >
                        <Icon size={20} strokeWidth={2.2} />
                      </div>
                      <div>
                        <div style={{ fontSize: 9.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)" }}>
                          {module.categoryLabel}
                        </div>
                        <div style={{ fontSize: 15, fontWeight: 800, color: "#111111", letterSpacing: "-0.01em" }}>
                          {module.name}
                        </div>
                      </div>
                    </div>

                    <span
                      className={`tag ${
                        module.tagType === "success"
                          ? "tag-success"
                          : module.tagType === "warning"
                          ? "tag-warning"
                          : module.tagType === "info"
                          ? "tag-info"
                          : ""
                      }`}
                      style={{ fontSize: 10 }}
                    >
                      {module.tag}
                    </span>
                  </div>

                  {/* Summary */}
                  <p style={{ fontSize: 12, color: "var(--text-secondary)", lineHeight: 1.55, marginBottom: 14 }}>
                    {module.summary}
                  </p>

                  {/* Feature Highlights */}
                  <div style={{ display: "flex", flexDirection: "column", gap: 5, marginBottom: 16 }}>
                    {module.features.map((feat, i) => (
                      <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "var(--text-muted)" }}>
                        <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#111111", flexShrink: 0 }} />
                        <span>{feat}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Card Footer: Live Chip & Action Link */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    paddingTop: 12,
                    borderTop: "1px solid var(--border-subtle)",
                    marginTop: 4,
                  }}
                >
                  <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text-muted)" }}>
                    {module.metricsPreview}
                  </span>

                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      fontSize: 12,
                      fontWeight: 700,
                      color: "#111111",
                    }}
                  >
                    Open <ArrowRight size={13} />
                  </span>
                </div>
              </div>
            </Link>
          );
        })}

        {/* ── Extensible Placeholder Card (Ready for New Modules) ── */}
        <div
          style={{
            background: "#fafafa",
            border: "1.5px dashed var(--border)",
            borderRadius: 14,
            padding: "24px 22px",
            minHeight: 220,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
            gap: 10,
          }}
        >
          <div
            style={{
              width: 38,
              height: 38,
              borderRadius: "50%",
              background: "#f3f4f6",
              border: "1px solid var(--border)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--text-muted)",
            }}
          >
            <Layers size={18} />
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "var(--text-primary)", marginBottom: 3 }}>
              Modular Architecture
            </div>
            <p style={{ fontSize: 11.5, color: "var(--text-muted)", maxWidth: 260, lineHeight: 1.4 }}>
              Additional custom analysis or predictive modules plug directly into this launchpad grid.
            </p>
          </div>
          <Link href="/upload" style={{ textDecoration: "none" }}>
            <span style={{ fontSize: 11.5, fontWeight: 700, color: "#111111", display: "inline-flex", alignItems: "center", gap: 4 }}>
              Upload Data to Power Modules <ArrowUpRight size={12} />
            </span>
          </Link>
        </div>
      </div>
    </div>
  );
}
