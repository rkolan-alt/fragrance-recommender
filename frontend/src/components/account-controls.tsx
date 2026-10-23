"use client";
import { useEffect, useRef, useState } from "react";
import type { Perfume } from "@/lib/types";
import type { User } from "@/lib/account";
import { accountRequest } from "@/lib/account-client";
import { parseCollection } from "@/lib/collection";

async function google(collection: Perfume[]) {
  const options = await accountRequest<{
    google_enabled: boolean;
    frontend_origin: string;
  }>("auth/options");
  if (!options.google_enabled)
    throw new Error(
      "Google sign-in is not configured yet. Use email to continue.",
    );
  const target = new URL(options.frontend_origin);
  if (target.origin !== window.location.origin) {
    // Localhost and 127.0.0.1 do not share cookies. Carry only guest fragrance
    // metadata to the configured site; credentials never enter the URL.
    target.searchParams.set("google", "1");
    target.hash = new URLSearchParams({
      guest: JSON.stringify(collection),
    }).toString();
    window.location.assign(target.href);
    return;
  }
  const result = await accountRequest<{ authorization_url: string }>(
    "auth/google/authorize",
  );
  const url = new URL(result.authorization_url);
  if (url.protocol !== "https:" || url.hostname !== "accounts.google.com")
    throw new Error("Unable to start Google sign-in.");
  window.location.assign(url.href);
}

export function AccountControls({
  user,
  collection,
  ready,
  refresh,
  logout,
  locked,
}: {
  user: User | null;
  collection: Perfume[];
  ready: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
  locked: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"login" | "signup" | "forgot">("login");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const transferred = useRef(false);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("google") === "1" && !transferred.current) {
      transferred.current = true;
      try {
        const local = parseCollection(
          new URLSearchParams(window.location.hash.slice(1)).get("guest"),
        );
        const existing = parseCollection(
          localStorage.getItem("fragrance-collection:v1"),
        );
        const merged = parseCollection(JSON.stringify([...existing, ...local]));
        localStorage.setItem("fragrance-collection:v1", JSON.stringify(merged));
        window.dispatchEvent(new Event("fragrance-collection-change"));
        window.history.replaceState(null, "", "/");
        google(merged).catch((err) => {
          setError(err.message);
          setOpen(true);
        });
      } catch {
        queueMicrotask(() => {
          setError(
            "Browser storage is needed to carry your guest collection into Google sign-in. You can sign in with email on the original page instead.",
          );
          setOpen(true);
        });
      }
    } else if (params.get("auth_error") === "google") {
      window.history.replaceState(null, "", "/");
      queueMicrotask(() => {
        setError(
          "Google sign-in couldn’t be completed. Try again, or sign in with email if you already have an account.",
        );
        setOpen(true);
      });
    } else if (params.has("signed_in"))
      window.history.replaceState(null, "", "/");
  }, []);
  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const node = dialog.current;
    node?.showModal();
    return () => {
      node?.close();
      previous?.focus();
    };
  }, [open]);
  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await work();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Please try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="account-controls">
      {user ? (
        <>
          <span className="account-email" title={user.email}>
            {user.email}
          </span>
          <button
            className="header-link"
            disabled={busy || locked}
            onClick={() => action(logout)}
          >
            Sign out
          </button>
          {!user.is_verified && (
            <button
              className="header-link"
              disabled={busy || locked}
              onClick={() =>
                action(async () => {
                  await accountRequest("auth/request-verify-token", {
                    method: "POST",
                    body: JSON.stringify({ email: user.email }),
                  });
                  setMessage(
                    "Verification requested. Check your email. In local development, messages are saved in backend/mail-outbox.",
                  );
                })
              }
            >
              Verify email
            </button>
          )}
        </>
      ) : (
        <button
          className="header-link"
          disabled={!ready}
          onClick={() => {
            setMode("login");
            setOpen(true);
            setError("");
            setMessage("");
          }}
        >
          {ready ? "Sign in / Save collection" : "Checking account…"}
        </button>
      )}
      {!open && error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!open && message && (
        <p className="fine-print" role="status">
          {message}
        </p>
      )}
      {open && (
        <dialog
          ref={dialog}
          className="detail-dialog account-dialog"
          aria-labelledby="account-title"
          onCancel={(event) => {
            event.preventDefault();
            if (!busy) setOpen(false);
          }}
        >
          <div className="detail-inner">
            <button
              className="round-button detail-close"
              aria-label="Close account"
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              ×
            </button>
            <p className="eyebrow">YOUR COLLECTION, WHEREVER YOU GO</p>
            <h2 id="account-title">
              {mode === "signup"
                ? "Make it yours."
                : mode === "forgot"
                  ? "Reset your password."
                  : "Welcome back."}
            </h2>
            <p className="fine-print">
              Your guest collection will be added to your account when you sign
              in.
            </p>
            {mode !== "forgot" && (
              <button
                className="secondary-button"
                disabled={busy}
                onClick={() => action(() => google(collection))}
              >
                Continue with Google
              </button>
            )}
            <form
              className="account-form"
              onSubmit={(event) => {
                event.preventDefault();
                const data = new FormData(event.currentTarget);
                const email = String(data.get("email"));
                const password = String(data.get("password") || "");
                void action(async () => {
                  if (mode === "forgot") {
                    await accountRequest("auth/forgot-password", {
                      method: "POST",
                      body: JSON.stringify({ email }),
                    });
                    setMessage(
                      "If an account exists, a reset link has been requested. In local development, open the message in backend/mail-outbox.",
                    );
                    return;
                  }
                  if (mode === "signup")
                    await accountRequest("auth/register", {
                      method: "POST",
                      body: JSON.stringify({ email, password }),
                    });
                  await accountRequest("auth/login", {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/x-www-form-urlencoded",
                    },
                    body: new URLSearchParams({
                      username: email,
                      password,
                    }).toString(),
                  });
                  await refresh();
                  setOpen(false);
                });
              }}
            >
              <label>
                Email
                <input
                  name="email"
                  type="email"
                  autoComplete="email"
                  required
                  maxLength={320}
                />
              </label>
              {mode !== "forgot" && (
                <label>
                  Password
                  <input
                    name="password"
                    type="password"
                    autoComplete={
                      mode === "signup" ? "new-password" : "current-password"
                    }
                    minLength={mode === "signup" ? 12 : 1}
                    maxLength={128}
                    required
                  />
                  {mode === "signup" && <small>Use 12–128 characters.</small>}
                </label>
              )}
              <button className="primary-button" disabled={busy}>
                {busy
                  ? "One moment…"
                  : mode === "signup"
                    ? "Create account"
                    : mode === "forgot"
                      ? "Send reset link"
                      : "Sign in"}
              </button>
            </form>
            {error && (
              <p className="error" role="alert">
                {error}
              </p>
            )}
            {message && (
              <p className="fine-print" role="status">
                {message}
              </p>
            )}
            <div className="account-links">
              <button
                disabled={busy}
                onClick={() => {
                  setMode(mode === "signup" ? "login" : "signup");
                  setError("");
                  setMessage("");
                }}
              >
                {mode === "signup"
                  ? "Already have an account? Sign in"
                  : "Create an account"}
              </button>
              <button
                disabled={busy}
                onClick={() => {
                  setMode(mode === "forgot" ? "login" : "forgot");
                  setError("");
                  setMessage("");
                }}
              >
                {mode === "forgot" ? "Back to sign in" : "Forgot password?"}
              </button>
            </div>
          </div>
        </dialog>
      )}
    </div>
  );
}
