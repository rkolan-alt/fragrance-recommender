"use client";
import { useEffect, useId, useRef, useState } from "react";
import { accountRequest } from "@/lib/account-client";
import type { User } from "@/lib/account";
type Provider = { provider: string; email: string };

export function AccountSettings({
  user,
  emailEnabled,
  disabled,
  sessionChanged,
}: {
  user: User;
  emailEnabled: boolean;
  disabled: boolean;
  sessionChanged: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [canonical, setCanonical] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const title = useId();
  useEffect(() => {
    const url = new URL(window.location.href);
    if (url.searchParams.has("google_connected")) {
      url.searchParams.delete("google_connected");
      window.history.replaceState(null, "", url);
      queueMicrotask(() => {
        setMessage("Google is now connected to your account.");
        setOpen(true);
      });
    } else if (url.searchParams.get("auth_error") === "google_link") {
      url.searchParams.delete("auth_error");
      window.history.replaceState(null, "", url);
      queueMicrotask(() => {
        setError(
          "Google couldn’t be connected. Try again with an account that is not already linked to another fragrance account.",
        );
        setOpen(true);
      });
    }
  }, []);
  useEffect(() => {
    if (!open) return;
    const node = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    node?.showModal();
    const controller = new AbortController();
    accountRequest<Provider[]>("me/oauth", { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setProviders(data);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError(
            "Connected accounts could not be loaded. Close and reopen settings to retry.",
          );
      });
    return () => {
      controller.abort();
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
    <>
      <button
        className="header-link"
        disabled={disabled}
        onClick={() => {
          setOpen(true);
          setError("");
          setMessage("");
        }}
      >
        Account settings
      </button>
      {open && (
        <dialog
          ref={dialog}
          className="detail-dialog account-dialog settings-dialog"
          aria-labelledby={title}
          onCancel={(e) => {
            e.preventDefault();
            if (!busy) setOpen(false);
          }}
        >
          <div className="detail-inner">
            <button
              className="round-button detail-close"
              aria-label="Close account settings"
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              ×
            </button>
            <p className="eyebrow">YOUR ACCOUNT</p>
            <h2 id={title}>A place for your taste.</h2>
            <p className="settings-email">
              {user.email}
              <small>
                {user.is_verified ? "Email verified" : "Email not yet verified"}
              </small>
            </p>
            <div className="settings-notice">
              {error && (
                <p className="error" role="alert">
                  {error}
                </p>
              )}
              {message && (
                <p role="status" className="fine-print">
                  {message}
                </p>
              )}
            </div>
            <fieldset disabled={busy} className="settings-fields">
              <section>
                <h3>Connected sign-in</h3>
                {providers === null ? (
                  <p role="status">Loading connected accounts…</p>
                ) : providers.some((p) => p.provider === "google") ? (
                  <ul className="connected-providers">
                    {providers.map((provider, index) => (
                      <li key={`${provider.provider}-${index}`}>
                        Google · {provider.email}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <>
                    <p className="fine-print">
                      Connect Google to sign in to this same account. Verify
                      your email first.
                    </p>
                    <button
                      className="secondary-button"
                      disabled={!user.is_verified}
                      onClick={() =>
                        action(async () => {
                          const options = await accountRequest<{
                            google_enabled: boolean;
                            frontend_origin: string;
                          }>("auth/options");
                          if (!options.google_enabled)
                            throw new Error(
                              "Google sign-in is not configured yet.",
                            );
                          const origin = new URL(options.frontend_origin);
                          if (origin.origin !== window.location.origin) {
                            setCanonical(origin.href);
                            throw new Error(
                              "Open the account site below and sign in there before connecting Google.",
                            );
                          }
                          const data = await accountRequest<{
                            authorization_url: string;
                          }>("auth/google/associate/authorize");
                          const url = new URL(data.authorization_url);
                          if (
                            url.protocol !== "https:" ||
                            url.hostname !== "accounts.google.com"
                          )
                            throw new Error(
                              "Couldn’t start Google account linking.",
                            );
                          window.location.assign(url.href);
                        })
                      }
                    >
                      Connect Google
                    </button>
                    {canonical && (
                      <p>
                        <a className="settings-link" href={canonical}>
                          Open account site →
                        </a>
                      </p>
                    )}
                  </>
                )}
              </section>
              {emailEnabled && (
                <section>
                  <h3>Change password</h3>
                  <form
                    className="account-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const form = e.currentTarget;
                      const data = new FormData(form);
                      if (data.get("new_password") !== data.get("confirmation")) {
                        setError("The new passwords do not match.");
                        return;
                      }
                      void action(async () => {
                        await accountRequest("me/password", {
                          method: "POST",
                          body: JSON.stringify({
                            current_password: data.get("current_password"),
                            new_password: data.get("new_password"),
                          }),
                        });
                        form.reset();
                        setOpen(false);
                        await sessionChanged();
                      });
                    }}
                  >
                    <p className="fine-print">
                      Changing your password signs out all sessions. Sign in again
                      with your new password.
                    </p>
                    <label>
                      Current password
                      <input
                        type="password"
                        name="current_password"
                        autoComplete="current-password"
                        required
                        maxLength={128}
                      />
                    </label>
                    <label>
                      New password
                      <input
                        type="password"
                        name="new_password"
                        autoComplete="new-password"
                        required
                        minLength={12}
                        maxLength={128}
                      />
                      <small>Use 12–128 characters.</small>
                    </label>
                    <label>
                      Confirm new password
                      <input
                        type="password"
                        name="confirmation"
                        autoComplete="new-password"
                        required
                        minLength={12}
                        maxLength={128}
                      />
                    </label>
                    <button className="secondary-button">
                      Change password & sign out
                    </button>
                  </form>
                  <p className="fine-print">
                    If you signed up with Google or forgot your password, request
                    a password-reset email to set one.
                  </p>
                  <button
                    className="settings-link"
                    onClick={() =>
                      action(async () => {
                        await accountRequest("auth/forgot-password", {
                          method: "POST",
                          body: JSON.stringify({ email: user.email }),
                        });
                        setMessage(
                          "Password reset requested. Follow the link in your email to set a new password.",
                        );
                      })
                    }
                  >
                    Request password-reset email
                  </button>
                </section>
              )}
              <section className="delete-account">
                <h3>Delete account</h3>
                <p className="fine-print">
                  This permanently removes your account, collection, saved
                  filters, Google connection, and activity. This cannot be
                  undone.
                </p>
                <form
                  className="account-form"
                  onSubmit={(e) => {
                    e.preventDefault();
                    const data = new FormData(e.currentTarget);
                    void action(async () => {
                      await accountRequest("me", {
                        method: "DELETE",
                        body: JSON.stringify({
                          confirmation_email: data.get("confirmation_email"),
                          confirmation_text: data.get("confirmation_text"),
                        }),
                      });
                      setOpen(false);
                      await sessionChanged();
                    });
                  }}
                >
                  <label>
                    Account email to confirm deletion
                    <input
                      type="email"
                      name="confirmation_email"
                      autoComplete="off"
                      required
                      maxLength={320}
                    />
                  </label>
                  <label>
                    Type DELETE to confirm
                    <input
                      name="confirmation_text"
                      autoComplete="off"
                      pattern="DELETE"
                      required
                    />
                  </label>
                  <button className="danger-button">
                    Permanently delete my account
                  </button>
                </form>
              </section>
            </fieldset>
          </div>
        </dialog>
      )}
    </>
  );
}
