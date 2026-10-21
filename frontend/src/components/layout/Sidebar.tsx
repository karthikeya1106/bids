"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, PieChart, AlertTriangle,
  Activity, TrendingUp, BarChart3, Zap, Upload, FileBarChart2,
} from "lucide-react";

const navItems = [
  { href: "/dashboard",    label: "Executive Dashboard",  icon: LayoutDashboard, section: "Modules" },
  { href: "/behavior",     label: "Behavior Analytics",   icon: Activity,        section: "Modules" },
  { href: "/segmentation", label: "Customer Segments",    icon: PieChart,        section: "Modules" },
  { href: "/rootcause",    label: "Root Cause Analysis",  icon: AlertTriangle,   section: "Modules" },
  { href: "/drift",        label: "Data Drift & BPR",     icon: BarChart3,       section: "Modules" },
  { href: "/forecasting",  label: "Forecast & Strategy",  icon: TrendingUp,      section: "Modules" },
  { href: "/analysis",     label: "Analysis Report",      icon: FileBarChart2,   section: "Intelligence" },
  { href: "/upload",       label: "Data Upload",          icon: Upload,          section: "Data" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const sections = Array.from(new Set(navItems.map(i => i.section)));

  return (
    <aside className="sidebar">
      {/* Logo */}
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">
          <Zap size={18} color="#ffffff" strokeWidth={2.5} />
        </div>
        <div className="sidebar-logo-text">
          <div className="sidebar-logo-title">BIDS</div>
          <div className="sidebar-logo-sub">Intelligence Platform</div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="sidebar-nav">
        {sections.map(section => (
          <div key={section}>
            <div className="sidebar-section-label">{section}</div>
            {navItems.filter(i => i.section === section).map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href || pathname.startsWith(item.href + "/");
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`nav-item ${isActive ? "active" : ""}`}
                >
                  <span className="nav-icon">
                    <Icon size={16} />
                  </span>
                  <span style={{ flex: 1 }}>{item.label}</span>
                  {isActive && (
                    <span style={{
                      width: 5, height: 5, borderRadius: "50%",
                      background: "#ffffff", flexShrink: 0,
                    }} />
                  )}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
    </aside>
  );
}
