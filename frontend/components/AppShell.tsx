"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useState } from "react";
import { api } from "../lib/api";
import { AuthUser, clearSession, getStoredUser, getToken, setSession } from "../lib/auth";

type Props = {
  children: ReactNode;
  mode: "chat" | "agent";
};

export function AppShell({ children, mode }: Props) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getToken();
    const stored = getStoredUser();
    if (!token) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    setUser(stored);
    void api
      .me()
      .then((profile) => {
        setSession(token, profile);
        setUser(profile);
        setReady(true);
      })
      .catch(() => {
        clearSession();
        router.replace("/login");
      });
  }, [pathname, router]);

  if (!ready || !user) {
    return (
      <div className="auth-screen">
        <p className="panel-muted">Loading Forge…</p>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark">F</span>
          <div>
            <strong>Forge</strong>
            <small>{user.display_name}</small>
          </div>
        </div>

        <nav className="mode-nav">
          <Link className={`mode-link ${mode === "chat" ? "active" : ""}`} href="/">
            Chat
          </Link>
          <Link className={`mode-link ${mode === "agent" ? "active" : ""}`} href="/agent">
            Agent
          </Link>
        </nav>

        <div className="sidebar-footer">
          <Link className="sidebar-quiet" href="/workspace">
            Code workspace
          </Link>
          <button
            type="button"
            className="sidebar-quiet"
            onClick={() => {
              clearSession();
              router.replace("/login");
            }}
          >
            Sign out
          </button>
        </div>
      </aside>
      <div className="app-main">{children}</div>
    </div>
  );
}
