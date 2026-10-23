"use client";
import Link from "next/link";
import { useState } from "react";
import { accountRequest } from "@/lib/account-client";
import { useAuthOptions } from "@/lib/auth-options";
export function AccountToken({ purpose }: { purpose: "verify" | "reset" }) {
  const { options, error: optionsError } = useAuthOptions();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  return (
    <main className="account-token">
      <p className="eyebrow">FRAGRANCE RECOMMENDER</p>
      <h1>{options && !options.email_password_enabled ? "Sign in with Google." : purpose === "verify" ? "Verify your email." : "A fresh start."}</h1>
      {!options ? (
        <p role="status">{optionsError || "Loading account options…"}</p>
      ) : !options.email_password_enabled ? (
        <p>Email/password accounts are unavailable on this site. Return to your collection and sign in with Google.</p>
      ) : done ? (
        <p role="status">
          {purpose === "verify"
            ? "Your email is verified."
            : "Password updated. Sign in with your new password."}
        </p>
      ) : (
        <form
          className="account-form"
          onSubmit={async (event) => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            const token = new URLSearchParams(window.location.search).get(
              "token",
            );
            if (!token) {
              setError("This link is missing its token. Request a new email.");
              return;
            }
            setBusy(true);
            setError("");
            try {
              await accountRequest(
                purpose === "verify" ? "auth/verify" : "auth/reset-password",
                {
                  method: "POST",
                  body: JSON.stringify({
                    token,
                    ...(purpose === "reset"
                      ? { password: data.get("password") }
                      : {}),
                  }),
                },
              );
              window.history.replaceState(null, "", window.location.pathname);
              setDone(true);
            } catch (err) {
              setError(
                err instanceof Error
                  ? err.message
                  : "Please request a new link.",
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          {purpose === "reset" && (
            <label>
              New password
              <input
                type="password"
                name="password"
                autoComplete="new-password"
                minLength={12}
                maxLength={128}
                required
              />
              <small>Use 12–128 characters.</small>
            </label>
          )}
          <button className="primary-button" disabled={busy}>
            {busy
              ? "One moment…"
              : purpose === "verify"
                ? "Verify email"
                : "Update password"}
          </button>
        </form>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <Link href="/">Back to your collection →</Link>
    </main>
  );
}
