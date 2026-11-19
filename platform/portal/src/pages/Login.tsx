import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api";
import { useAuth } from "../auth";
import { copy } from "../copy";
import { Button, ErrorBox, Field } from "../ui";
import { AuthShell } from "./AuthShell";

function loginErrorMessage(err: unknown): string {
  // Generic on 401: never reveals whether the email exists.
  if (err instanceof ApiError) {
    if (err.status === 401) return copy.auth.errors.invalidCredentials;
    if (err.status === 429) return copy.auth.errors.tooMany;
    if (err.status === 0) return copy.auth.errors.network;
    if (err.status >= 500) return copy.auth.errors.server;
    return copy.auth.errors.generic;
  }
  return copy.auth.errors.invalidCredentials;
}

export function Login() {
  const { me, loading, login } = useAuth();
  const nav = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // null = still asking the server; true = show password reset link; false = disabled note
  const [canReset, setCanReset] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    api.capabilities().then((c) => alive && setCanReset(c.password_reset));
    return () => {
      alive = false;
    };
  }, []);
  const target = from?.startsWith("/app") ? from : "/app";

  if (!loading && me) return <Navigate to={target} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      nav(target, { replace: true });
    } catch (err) {
      setError(loginErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell
      title={copy.auth.login.pageTitle}
      eyebrow={copy.auth.login.eyebrow}
      sheetCode={copy.auth.login.sheetCode}
      art="horizon"
    >
      <h1 className="heading text-3xl sm:text-5xl">{copy.auth.login.title}</h1>
      <p className="mt-3 text-subtle">{copy.auth.login.subtitle}</p>
      <form onSubmit={submit} className="mt-8 flex flex-col gap-6">
        <Field
          label={copy.auth.login.emailLabel}
          id="email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label={copy.auth.login.passwordLabel}
          id="password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aside={
            canReset === true ? (
              <Link to="/forgot-password" className="link text-sm">
                {copy.auth.login.forgotLink}
              </Link>
            ) : undefined
          }
        />
        {error && <ErrorBox>{error}</ErrorBox>}
        <Button type="submit" variant="primary" size="lg" disabled={busy} className="mt-2 w-full">
          {busy ? copy.auth.login.submitting : copy.auth.login.submit}
        </Button>
      </form>
      {canReset === false && (
        <p className="mt-6 border-t border-line pt-4 text-sm text-subtle">{copy.auth.login.resetDisabledNote}</p>
      )}
    </AuthShell>
  );
}
