import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { Button, Card, ErrorBox, Field, Title } from "../ui";

export function Login() {
  const { me, loading, login } = useAuth();
  const nav = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
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
    <div className="flex h-full items-center bg-tint">
      <div className="container-page grid w-full grid-cols-12 items-center gap-x-0 lg:gap-x-12 gap-y-12 py-24">
        <div className="col-span-12 flex flex-col gap-6 lg:col-span-6">
          <Title className="text-5xl lg:text-6xl">Log in</Title>
          <p className="max-w-md text-lg text-subtle">
            Use the email and password your organization's admin created for you. If you do not have access yet, ask an
            admin.
          </p>
        </div>
        <div className="col-span-12 lg:col-span-5 lg:col-start-8">
          <Card shadow className="p-8">
            <form onSubmit={submit} className="flex flex-col gap-6">
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
              />
              {error && <ErrorBox>{error}</ErrorBox>}
              <Button type="submit" variant="primary" size="lg" disabled={busy}>
                {busy ? "Logging in…" : "Log In"}
              </Button>
            </form>
          </Card>
        </div>
      </div>
    </div>
  );
}
