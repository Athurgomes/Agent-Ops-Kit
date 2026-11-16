import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../../api";
import { useOps } from "../../opsAuth";
import { Button, ErrorBox, Field } from "../../ui";
import { OpsBar } from "./OpsLayout";

export function OpsLogin() {
  const { status, login } = useOps();
  const nav = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from;
  const target = from?.startsWith("/ops") && from !== "/ops/login" ? from : "/ops/organizations";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (status === "authed") return <Navigate to={target} replace />;

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
    <div className="min-h-screen">
      <OpsBar />
      <main id="content" className="flex flex-col items-center px-6 py-12">
        <div className="box w-full max-w-md p-8 sm:p-12">
          <h1 className="heading text-4xl sm:text-5xl">Operator sign in</h1>
          <p className="mt-3 text-subtle">This console is for platform operators. It is not the sign in of an organization.</p>
          <form onSubmit={submit} className="mt-8 flex flex-col gap-6">
            <Field label="Email" id="ops-email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
            <Field
              label="Password"
              id="ops-password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {error && <ErrorBox>{error}</ErrorBox>}
            <Button type="submit" variant="primary" size="lg" disabled={busy} className="mt-2 w-full">
              {busy ? "Logging in…" : "Log In"}
            </Button>
          </form>
        </div>
      </main>
    </div>
  );
}
