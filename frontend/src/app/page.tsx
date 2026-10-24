import Link from "next/link";
import {
  Activity, AlertTriangle, ArrowRight, BarChart3, CheckCircle2,
  FileBarChart2, LayoutDashboard, PieChart, ShieldCheck, Sparkles,
  TrendingUp, Upload, Zap,
} from "lucide-react";

const FEATURES = [
  {
    icon: LayoutDashboard,
    title: "Executive dashboard",
    copy: "The numbers a leadership team actually needs, with every KPI compared against the previous period.",
    points: ["Revenue, profit, margin and AOV deltas", "Monthly trend with category and region mix", "Alerts generated from the data itself"],
  },
  {
    icon: Activity,
    title: "Behavior analytics",
    copy: "How customers buy: cadence, retention, discount sensitivity and the products that keep them coming back.",
    points: ["Quarterly cohort retention matrix", "Lifecycle funnel with conversion rates", "Discount bands and their real margin"],
  },
  {
    icon: PieChart,
    title: "Customer segments",
    copy: "RFM quintile scoring feeds K-Means clustering, then clusters are ranked into four business segments.",
    points: ["Champions, At-Risk, New / Growing, Lost", "Revenue share per segment", "Top customers with names and spend"],
  },
  {
    icon: AlertTriangle,
    title: "Root cause analysis",
    copy: "Anomaly detection on monthly revenue, explained through a weighted fishbone of operational causes.",
    points: ["Z-score anomaly months", "Six scored causal branches", "Evidence strings with real values"],
  },
  {
    icon: BarChart3,
    title: "Drift & BPR rules",
    copy: "ADWIN watches every KPI stream for distribution shifts, while business rules stay reviewable and editable.",
    points: ["Per-KPI drift scores", "Rule effectiveness and status", "Inline rule editing"],
  },
  {
    icon: TrendingUp,
    title: "Forecast & strategy",
    copy: "Six-month revenue forecasts, what-if elasticity simulation and an AI strategy brief you can act on.",
    points: ["XGBoost with trend fallback", "Price / discount / marketing sliders", "Gemini or rule-based recommendations"],
  },
];

const MODULES = [
  { name: "Executive Dashboard", copy: "Trailing-period KPIs, trend, mix and alerts", href: "/dashboard" },
  { name: "Behavior Analytics", copy: "Cohorts, funnel, discount bands, cadence", href: "/behavior" },
  { name: "Customer Segments", copy: "K-Means RFM segments and revenue share", href: "/segmentation" },
  { name: "Root Cause Analysis", copy: "Anomalies and a scored fishbone", href: "/rootcause" },
  { name: "Data Drift & BPR", copy: "ADWIN drift monitoring and rule reviews", href: "/drift" },
  { name: "Forecast & Strategy", copy: "Forecasts, what-if and recommendations", href: "/forecasting" },
  { name: "Analysis Report", copy: "Health score, benchmarks and action items", href: "/analysis" },
  { name: "Data Upload", copy: "CSV or Excel with 16-field auto-mapping", href: "/upload" },
];

const STEPS = [
  {
    title: "Bring your data",
    copy: "Drop in a CSV or Excel export. BIDS detects what each column means across 16 canonical fields — order date, revenue, discount, region and more — and asks only for what it cannot infer.",
  },
  {
    title: "Let the models run",
    copy: "RFM quintiles and K-Means build segments. ADWIN measures drift on every KPI stream. Anomaly detection and XGBoost handle the trend line. No numbers are mocked.",
  },
  {
    title: "Decide with evidence",
    copy: "Every chart links back to the rows behind it, and the analysis report turns the results into a ranked action list with a 0–100 organizational health score.",
  },
];

const HERO_BARS = [38, 52, 44, 68, 59, 74, 63, 88, 71, 95, 82, 100];

export default function LandingPage() {
  return (
    <div className="landing">
      <header className="landing-nav">
        <div className="landing-wrap landing-nav-inner">
          <Link href="/" className="landing-brand">
            <span className="landing-brand-mark">
              <Zap size={18} color="#ffffff" strokeWidth={2.5} />
            </span>
            <span>
              <span className="landing-brand-name">BIDS</span>
              <br />
              <span className="landing-brand-sub">Decision intelligence</span>
            </span>
          </Link>

          <nav className="landing-links" aria-label="Landing sections">
            <a href="#features" className="landing-link">Features</a>
            <a href="#workflow" className="landing-link">How it works</a>
            <a href="#modules" className="landing-link">Modules</a>
          </nav>

          <div className="landing-actions">
            <Link href="/login" className="btn-ghost">Sign in</Link>
            <Link href="/login" className="btn-primary">
              Open dashboard <ArrowRight size={14} />
            </Link>
          </div>
        </div>
      </header>

      <main>
        {/* ── Hero ─────────────────────────────────────────────────────── */}
        <section className="landing-wrap landing-hero">
          <div>
            <div className="landing-eyebrow">
              <Sparkles size={12} /> Business Intelligence Decision System
            </div>
            <h1 className="landing-h1">
              Turn sales data into decisions you can defend.
            </h1>
            <p className="landing-lede">
              BIDS ingests your order history and builds the whole analytical stack on top of it —
              executive KPIs, customer behavior, RFM segments, root-cause analysis, drift monitoring
              and forecasts. Every figure is computed from your data, not from sample constants.
            </p>
            <div className="landing-cta-row">
              <Link href="/login" className="btn-primary landing-cta">
                Enter the workspace <ArrowRight size={16} />
              </Link>
              <a href="#features" className="btn-ghost landing-cta">See what&apos;s inside</a>
            </div>
            <div className="landing-micro">
              <span><CheckCircle2 size={13} /> Runs locally</span>
              <span><ShieldCheck size={13} /> Your data stays on your machine</span>
              <span><Zap size={13} /> Demo login available</span>
            </div>
          </div>

          {/* Product preview */}
          <div className="landing-hero-panel" aria-hidden="true">
            <div className="landing-panel-head">
              <span className="landing-panel-title">Executive snapshot</span>
              <span className="landing-panel-dot">
                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#10b981" }} />
                Sample workspace
              </span>
            </div>

            <div className="landing-mini-grid">
              <div className="landing-mini">
                <div className="landing-mini-label">Revenue</div>
                <div className="landing-mini-value">$2.30M</div>
                <div className="landing-mini-delta">5,009 orders</div>
              </div>
              <div className="landing-mini">
                <div className="landing-mini-label">Profit</div>
                <div className="landing-mini-value">$286K</div>
                <div className="landing-mini-delta">12.5% margin</div>
              </div>
              <div className="landing-mini">
                <div className="landing-mini-label">Customers</div>
                <div className="landing-mini-value">793</div>
                <div className="landing-mini-delta">4 regions</div>
              </div>
              <div className="landing-mini">
                <div className="landing-mini-label">Avg order</div>
                <div className="landing-mini-value">$459</div>
                <div className="landing-mini-delta">3 categories</div>
              </div>
            </div>

            <div className="landing-bars">
              {HERO_BARS.map((height, index) => (
                <div
                  key={index}
                  className={`landing-bar${index % 4 === 0 ? " muted" : ""}`}
                  style={{ height: `${height}%` }}
                />
              ))}
            </div>

            <div className="landing-panel-alert">
              <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>Furniture is carrying $742K of revenue at a 2.5% margin — the discount policy needs review.</span>
            </div>
          </div>
        </section>

        {/* ── Stats strip ──────────────────────────────────────────────── */}
        <section className="landing-stats">
          <div className="landing-wrap landing-stats-grid">
            <div>
              <div className="landing-stat-value">8</div>
              <div className="landing-stat-label">Analytics modules</div>
            </div>
            <div>
              <div className="landing-stat-value">16</div>
              <div className="landing-stat-label">Fields auto-mapped on upload</div>
            </div>
            <div>
              <div className="landing-stat-value">4</div>
              <div className="landing-stat-label">Models: K-Means, ADWIN, XGBoost, RFM</div>
            </div>
            <div>
              <div className="landing-stat-value">100%</div>
              <div className="landing-stat-label">Computed from loaded rows</div>
            </div>
          </div>
        </section>

        {/* ── Features ─────────────────────────────────────────────────── */}
        <section className="landing-wrap landing-section" id="features">
          <div className="landing-section-head">
            <div className="landing-section-kicker">The platform</div>
            <h2 className="landing-h2">Six ways to look at the same truth.</h2>
            <p className="landing-sub">
              Each module answers a different question, and they all read the same tables — so the
              dashboard, the segments and the report never disagree with each other.
            </p>
          </div>

          <div className="landing-features">
            {FEATURES.map(({ icon: Icon, title, copy, points }) => (
              <article className="landing-feature" key={title}>
                <div className="landing-feature-icon">
                  <Icon size={18} color="#000000" />
                </div>
                <h3 className="landing-feature-title">{title}</h3>
                <p className="landing-feature-copy">{copy}</p>
                <ul className="landing-feature-list">
                  {points.map((point) => (
                    <li key={point}>
                      <CheckCircle2 size={12} style={{ marginTop: 2, flexShrink: 0 }} />
                      <span>{point}</span>
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>

        {/* ── Workflow ─────────────────────────────────────────────────── */}
        <section className="landing-wrap landing-section" id="workflow">
          <div className="landing-section-head">
            <div className="landing-section-kicker">How it works</div>
            <h2 className="landing-h2">From spreadsheet to strategy in three steps.</h2>
            <p className="landing-sub">
              No configuration files, no warehouse project. Upload once and the platform recalculates
              every module, KPI and alert against the new data.
            </p>
          </div>

          <div className="landing-steps">
            {STEPS.map((step, index) => (
              <article className="landing-step" key={step.title}>
                <div className="landing-step-index">{index + 1}</div>
                <h3 className="landing-step-title">{step.title}</h3>
                <p className="landing-step-copy">{step.copy}</p>
              </article>
            ))}
          </div>
        </section>

        {/* ── Modules ──────────────────────────────────────────────────── */}
        <section className="landing-wrap landing-section" id="modules" style={{ paddingTop: 0 }}>
          <div className="landing-section-head">
            <div className="landing-section-kicker">Inside the workspace</div>
            <h2 className="landing-h2">Every module, already connected.</h2>
            <p className="landing-sub">
              Sign in to explore all eight. The sample dataset is loaded so you can see real output
              immediately.
            </p>
          </div>

          <div className="landing-modules">
            {MODULES.map((module) => (
              <Link key={module.name} href={module.href} className="landing-module">
                <div
                  style={{
                    width: 32, height: 32, borderRadius: 9, background: "#f3f4f6",
                    border: "1px solid var(--border)", display: "flex", alignItems: "center",
                    justifyContent: "center", flexShrink: 0,
                  }}
                >
                  <FileBarChart2 size={15} color="#111111" />
                </div>
                <div style={{ flex: 1 }}>
                  <div className="landing-module-name">{module.name}</div>
                  <div className="landing-module-copy">{module.copy}</div>
                </div>
                <ArrowRight size={14} style={{ marginTop: 8, color: "#9ca3af", flexShrink: 0 }} />
              </Link>
            ))}
          </div>
        </section>

        {/* ── CTA ──────────────────────────────────────────────────────── */}
        <div className="landing-wrap">
          <section className="landing-cta-band">
            <div>
              <h2>Ready to see your numbers?</h2>
              <p>
                Sign in with the demo account and land straight on the executive dashboard — no
                configuration required. Upload your own dataset whenever you want.
              </p>
            </div>
            <Link href="/login" className="btn-primary">
              Open the dashboard <ArrowRight size={15} />
            </Link>
          </section>
        </div>
      </main>

      <footer className="landing-footer">
        <div className="landing-wrap landing-footer-inner">
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span className="landing-brand-mark" style={{ width: 26, height: 26, borderRadius: 8 }}>
              <Zap size={13} color="#ffffff" strokeWidth={2.5} />
            </span>
            <span>
              BIDS · <Upload size={11} style={{ display: "inline", verticalAlign: -1 }} /> FastAPI,
              scikit-learn, XGBoost, River
            </span>
          </div>
          <div style={{ display: "flex", gap: 20 }}>
            <Link href="/login">Sign in</Link>
            <Link href="/signup">Create account</Link>
            <a href="#features">Features</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
