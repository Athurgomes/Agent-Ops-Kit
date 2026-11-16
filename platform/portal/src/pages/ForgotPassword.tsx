import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { Button, Field } from "../ui";
import { AuthShell } from "./AuthShell";

export const FORGOT_MESSAGE = "If an account exists for that email, we've sent a reset link. It expires in 30 minutes.";

export function ForgotPassword() {
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const status = await api.forgotPassword(email.trim());
    if (status === 404) {
      nav("/login", { replace: true }); // recovery is switched off on this server
      return;
    }
    // The same message for every other outcome (sent, unknown email, rate limit, network error): reveal nothing.
    setSent(true);
    setBusy(false);
  }

  return (
    <AuthShell title="Reset password">
      <h1 className="heading text-4xl sm:text-5xl">Forgot password?</h1>
      {sent ? (
        <>
          <p role="status" className="mt-6 box border-l-4 border-l-accent p-4 font-semibold">
            {FORGOT_MESSAGE}
          </p>
          <p className="mt-8">
            <Link to="/login" className="link">
              Back to Log In
            </Link>
          </p>
        </>
      ) : (
        <>
          <p className="mt-3 text-subtle">Enter your email and we'll send you a link to choose a new password.</p>
          <form onSubmit={submit} className="mt-8 flex flex-col gap-6">
            <Field label="Email" id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
            <Button type="submit" variant="primary" size="lg" disabled={busy} className="mt-2 w-full">
              {busy ? "Sending…" : "Send reset link"}
            </Button>
          </form>
          <p className="mt-8 text-sm">
            <Link to="/login" className="link">
              Back to Log In
            </Link>
          </p>
        </>
      )}
    </AuthShell>
  );
}
