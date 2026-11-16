import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Button, ErrorBox, Field, LinkButton } from "../ui";
import { AuthShell } from "./AuthShell";

const MIN = 12;
type Phase = "form" | "done" | "invalid" | "toomany";

/** Reads #token=... (read only; the URL is cleaned in an effect right after the first render). */
function readToken(): string | null {
  return new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token") || null;
}

export function ResetPassword() {
  // The token lives only in React state. It is never stored, logged or kept in the address bar.
  const [token, setToken] = useState<string | null>(readToken);
  const [phase, setPhase] = useState<Phase>(() => (readToken() ? "form" : "invalid"));
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const clean = () => window.history.replaceState(null, "", window.location.pathname + window.location.search);
    if (window.location.hash) clean();
    // a second email link opened in this same tab only changes the fragment: pick the new token up too
    const onHash = () => {
      const t = readToken();
      if (t) {
        setToken(t);
        setPassword("");
        setConfirm("");
        setPhase("form");
        setError(null);
        clean();
      }
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < MIN) {
      setError(`Use at least ${MIN} characters for the new password.`);
      return;
    }
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    const status = await api.resetPassword(token ?? "", password);
    setBusy(false);
    if (status === 204) {
      setToken(null);
      setPassword("");
      setConfirm("");
      setPhase("done");
    } else if (status === 400) {
      setToken(null);
      setPassword("");
      setConfirm("");
      setPhase("invalid");
    } else if (status === 429) setPhase("toomany");
    else if (status === 422) setError(`The new password needs at least ${MIN} characters.`);
    else setError("Could not reach the server. Please try again.");
  }

  if (phase === "done")
    return (
      <AuthShell title="Password updated">
        <h1 className="heading text-4xl sm:text-5xl">Password updated</h1>
        <p role="status" className="mt-3 text-subtle">
          Your password was changed and every session was signed out. Log in with the new password.
        </p>
        <div className="mt-8">
          <LinkButton to="/login" variant="primary" size="lg" className="w-full">
            Log In
          </LinkButton>
        </div>
      </AuthShell>
    );

  if (phase === "invalid")
    return (
      <AuthShell title="Link not valid">
        <h1 className="heading text-4xl sm:text-5xl">Link not valid</h1>
        <p role="alert" className="mt-3 font-semibold">
          This link is invalid or has expired.
        </p>
        <p className="mt-6">
          <Link to="/forgot-password" className="link">
            Ask for a new link
          </Link>
        </p>
        <p className="mt-4 text-sm">
          <Link to="/login" className="link">
            Back to Log In
          </Link>
        </p>
      </AuthShell>
    );

  if (phase === "toomany")
    return (
      <AuthShell title="Too many attempts">
        <h1 className="heading text-4xl sm:text-5xl">Too many attempts</h1>
        <p role="alert" className="mt-3 font-semibold">
          Too many attempts. Try again later.
        </p>
        <p className="mt-6 text-sm">
          <Link to="/login" className="link">
            Back to Log In
          </Link>
        </p>
      </AuthShell>
    );

  const type = show ? "text" : "password";
  return (
    <AuthShell title="Choose a new password">
      <h1 className="heading text-4xl sm:text-5xl">New password</h1>
      <p className="mt-3 text-subtle">Choose a new password for your account.</p>
      <form onSubmit={submit} noValidate className="mt-8 flex flex-col gap-6">
        <Field
          label="New password"
          id="new-password"
          type={type}
          autoComplete="new-password"
          required
          minLength={MIN}
          maxLength={256}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint={`At least ${MIN} characters.`}
          autoFocus
        />
        <Field
          label="Confirm password"
          id="confirm-password"
          type={type}
          autoComplete="new-password"
          required
          minLength={MIN}
          maxLength={256}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <label className="flex items-center gap-3 text-sm font-semibold">
          <input type="checkbox" checked={show} onChange={(e) => setShow(e.target.checked)} className="size-5 accent-[#2563eb]" />
          Show passwords
        </label>
        {error && <ErrorBox>{error}</ErrorBox>}
        <Button type="submit" variant="primary" size="lg" disabled={busy} className="mt-2 w-full">
          {busy ? "Saving…" : "Update password"}
        </Button>
      </form>
    </AuthShell>
  );
}
