import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api";
import { useAuth } from "../auth";
import { Button, ErrorBox, Field, Logo } from "../ui";

export function Login() {
  const { me, loading, login } = useAuth();
  const nav = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // null = still asking the server; true = show password reset link; false = hide link
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
      // generic error: never reveals whether the email exists
      setError(err instanceof ApiError && err.status !== 401 ? err.message : "Invalid email or password.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main id="content" className="flex min-h-screen flex-col items-center px-6 py-12">
      <Logo size="text-4xl" />
      <div className="box mt-12 w-full max-w-md p-8 sm:p-12">
        <h1 className="heading text-4xl sm:text-5xl">Welcome back</h1>
        <p className="mt-3 text-subtle">Sign in to read your agents' reports</p>
        <form onSubmit={submit} className="mt-8 flex flex-col gap-6">
          <Field
            label="Email"
            id="email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Field
            label="Password"
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aside={
              canReset === true ? (
                <Link to="/forgot-password" className="link text-sm">
                  Forgot password?
                </Link>
              ) : undefined
            }
          />
          {error && <ErrorBox>{error}</ErrorBox>}
          <Button type="submit" variant="primary" size="lg" disabled={busy} className="mt-2 w-full">
            {busy ? "Logging in…" : "Log In"}
          </Button>
        </form>
      </div>
    </main>
  );
}
