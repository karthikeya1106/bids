"use client";
import { Bell, RefreshCw, ChevronRight, LogOut, User } from "lucide-react";
import { useEffect, useState, useRef } from "react";
import { usePathname } from "next/navigation";
import { useSession, signOut } from "next-auth/react";

const PAGE_LABELS: Record<string, string> = {
  "/home":         "Home · Module Launchpad",
  "/dashboard":    "Executive Dashboard",
  "/behavior":     "Behavior Analytics",
  "/segmentation": "Customer Segments",
  "/rootcause":    "Root Cause Analysis",
  "/drift":        "Data Drift & BPR",
  "/forecasting":  "Forecast & Strategy",
  "/analysis":     "Analysis Report",
  "/upload":       "Data Upload",
};

export default function TopBar() {
  const pathname = usePathname();
  const { data: session } = useSession();
  const [time, setTime] = useState("");
  const [date, setDate] = useState("");
  const [showMenu, setShowMenu] = useState(false);
  // Which avatar URL failed to load. Tracking the URL itself means a different
  // account (new URL) is retried automatically, with no reset effect.
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setTime(now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }));
      setDate(now.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" }));
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  // Close menu when clicking outside
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenu(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const pageLabel = PAGE_LABELS[pathname] ?? "BIDS Platform";

  // Get user initials from session
  const userInitials = session?.user?.name
    ? session.user.name.split(" ").map((n: string) => n[0]).join("").toUpperCase().slice(0, 2)
    : "U";

  // Only trust an absolute http(s) URL, and fall back to initials when the
  // avatar cannot be fetched (blocked host, revoked Google photo, offline).
  const rawImage = session?.user?.image?.trim() ?? "";
  const usableImage = /^https?:\/\//i.test(rawImage) ? rawImage : "";
  const userImage = usableImage && failedSrc !== usableImage ? usableImage : "";

  return (
    <header className="topbar">
      {/* Left — breadcrumb */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 12, color: "var(--text-muted)", fontWeight: 600 }}>BIDS</span>
        <ChevronRight size={13} style={{ color: "var(--text-muted)" }} />
        <span style={{ fontSize: 13, color: "var(--text-primary)", fontWeight: 700 }}>{pageLabel}</span>
      </div>

      {/* Center — live clock */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          background: "var(--bg-raised)", border: "1px solid var(--border)",
          borderRadius: 8, padding: "5px 12px",
        }}>
          <div style={{
            width: 7, height: 7, borderRadius: "50%",
            background: "#10b981", boxShadow: "0 0 6px rgba(16,185,129,0.5)",
          }} />
          <span className="mono" style={{ fontSize: 13, color: "var(--text-primary)", fontWeight: 700, letterSpacing: "0.05em" }}>
            {time}
          </span>
          <span style={{ fontSize: 11, color: "var(--text-muted)", fontWeight: 500 }}>{date}</span>
        </div>
      </div>

      {/* Right — actions + avatar */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <button className="btn-ghost" style={{ padding: "6px 11px", fontSize: 12 }} onClick={() => window.location.reload()}>
          <RefreshCw size={13} />
          Refresh
        </button>

        {/* Notification bell */}
        <button className="btn-ghost" style={{ padding: "6px 10px", position: "relative" }}>
          <Bell size={15} />
          <span style={{
            position: "absolute", top: 4, right: 4,
            width: 7, height: 7, borderRadius: "50%",
            background: "#000000",
            border: "1.5px solid #ffffff",
          }} />
        </button>

        {/* Avatar + dropdown */}
        <div ref={menuRef} style={{ position: "relative" }}>
          <button
            onClick={() => setShowMenu(!showMenu)}
            style={{
              width: 32, height: 32, borderRadius: "50%",
              background: "#000000",
              border: "1px solid var(--border)",
              display: "flex", alignItems: "center", justifyItems: "center", justifyContent: "center",
              cursor: "pointer", padding: 0, overflow: "hidden",
              boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
            }}
            id="user-avatar-btn"
          >
            {userImage ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={userImage}
                alt=""
                referrerPolicy="no-referrer"
                onError={() => setFailedSrc(userImage)}
                style={{ width: "100%", height: "100%", objectFit: "cover" }}
              />
            ) : (
              <span style={{ fontSize: 11, fontWeight: 800, color: "#ffffff" }}>{userInitials}</span>
            )}
          </button>

          {/* Dropdown menu */}
          {showMenu && (
            <div style={{
              position: "absolute", top: "calc(100% + 8px)", right: 0,
              width: 220, background: "#ffffff",
              border: "1px solid var(--border)", borderRadius: 12,
              boxShadow: "0 12px 32px rgba(0,0,0,0.12)",
              overflow: "hidden", zIndex: 100,
            }}>
              {session?.user && (
                <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: "var(--text-primary)", marginBottom: 2 }}>
                    {session.user.name}
                  </div>
                  <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{session.user.email}</div>
                </div>
              )}
              <div style={{ padding: 6 }}>
                <button
                  style={{
                    width: "100%", display: "flex", alignItems: "center", gap: 10,
                    padding: "9px 12px", background: "transparent", border: "none",
                    borderRadius: 8, cursor: "pointer", color: "var(--text-secondary)",
                    fontSize: 13, fontFamily: "inherit", fontWeight: 500,
                    transition: "background 0.15s, color 0.15s",
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#f3f4f6"; (e.currentTarget as HTMLElement).style.color = "#000000"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; (e.currentTarget as HTMLElement).style.color = "var(--text-secondary)"; }}
                  onClick={() => { setShowMenu(false); }}
                >
                  <User size={14} /> Profile
                </button>
                <button
                  style={{
                    width: "100%", display: "flex", alignItems: "center", gap: 10,
                    padding: "9px 12px", background: "transparent", border: "none",
                    borderRadius: 8, cursor: "pointer", color: "#dc2626",
                    fontSize: 13, fontFamily: "inherit", fontWeight: 600,
                    transition: "background 0.15s",
                  }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = "#fef2f2"; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}
                  id="signout-btn"
                  onClick={() => signOut({ callbackUrl: "/login" })}
                >
                  <LogOut size={14} /> Sign out
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
