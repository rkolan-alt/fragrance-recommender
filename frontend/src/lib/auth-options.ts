"use client";
import { useEffect, useState } from "react";
import { accountRequest } from "./account-client";

export type AuthOptions = {
  google_enabled: boolean;
  email_password_enabled: boolean;
  frontend_origin: string;
};

export function useAuthOptions() {
  const [options, setOptions] = useState<AuthOptions | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    accountRequest<AuthOptions>("auth/options", { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) setOptions(value);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError("Sign-in options could not be loaded. Refresh to retry, or continue as a guest.");
      });
    return () => controller.abort();
  }, []);
  return { options, error };
}
