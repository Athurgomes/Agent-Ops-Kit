import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { copy } from "../copy";
import { Button, Field } from "../ui";
import { AuthShell } from "./AuthShell";

export const FORGOT_MESSAGE = copy.auth.forgot.sentMessage;

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
    <AuthShell
      title={copy.auth.forgot.pageTitle}
      sheetCode={copy.auth.forgot.sheetCode}
      art="compass"
    >
      <h1 className="heading text-3xl sm:text-5xl">{copy.auth.forgot.title}</h1>
      {sent ? (
        <>
          <p role="status" className="mt-6 border border-ink border-l-4 border-l-accent bg-surface p-4 font-semibold text-ink">
            {FORGOT_MESSAGE}
          </p>
          <p className="mt-8 text-sm">
            <Link to="/login" className="link">
              {copy.auth.forgot.backToLogin}
            </Link>
          </p>
        </>
      ) : (
        <>
          <p className="mt-3 text-subtle">{copy.auth.forgot.subtitle}</p>
          <form onSubmit={submit} className="mt-8 flex flex-col gap-6">
            <Field
              label={copy.auth.forgot.emailLabel}
              id="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
            />
            <Button type="submit" variant="primary" size="lg" disabled={busy} className="mt-2 w-full">
              {busy ? copy.auth.forgot.submitting : copy.auth.forgot.submit}
            </Button>
          </form>
          <p className="mt-8 text-sm">
            <Link to="/login" className="link">
              {copy.auth.forgot.backToLogin}
            </Link>
          </p>
        </>
      )}
    </AuthShell>
  );
}
