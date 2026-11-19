import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { copy } from "../copy";
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
      setError(copy.auth.reset.minLengthError(MIN));
      return;
    }
    if (password !== confirm) {
      setError(copy.auth.reset.mismatchError);
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
    else if (status === 422) setError(copy.auth.reset.serverMinLengthError(MIN));
    else setError(copy.auth.errors.network);
  }

  if (phase === "done")
    return (
      <AuthShell
        title={copy.auth.reset.donePageTitle}
        eyebrow={copy.auth.reset.eyebrow}
        sheetCode={copy.auth.reset.sheetCode}
        art="compass"
      >
        <h1 className="heading text-3xl sm:text-5xl">{copy.auth.reset.doneTitle}</h1>
        <p role="status" className="mt-6 border border-ink border-l-4 border-l-accent bg-surface p-4 text-ink">
          {copy.auth.reset.doneMessage}
        </p>
        <div className="mt-8">
          <LinkButton to="/login" variant="primary" size="lg" className="w-full">
            {copy.auth.reset.doneAction}
          </LinkButton>
        </div>
      </AuthShell>
    );

  if (phase === "invalid")
    return (
      <AuthShell
        title={copy.auth.reset.invalidPageTitle}
        eyebrow={copy.auth.reset.eyebrow}
        sheetCode={copy.auth.reset.sheetCode}
        art="compass"
      >
        <h1 className="heading text-3xl sm:text-5xl">{copy.auth.reset.invalidTitle}</h1>
        <div className="mt-6">
          <ErrorBox>{copy.auth.reset.invalidMessage}</ErrorBox>
        </div>
        <div className="mt-8 flex flex-col gap-4">
          <LinkButton to="/forgot-password" variant="primary" size="lg" className="w-full">
            {copy.auth.reset.requestNewLink}
          </LinkButton>
          <p className="text-sm">
            <Link to="/login" className="link">
              {copy.auth.reset.backToLogin}
            </Link>
          </p>
        </div>
      </AuthShell>
    );

  if (phase === "toomany")
    return (
      <AuthShell
        title={copy.auth.reset.tooManyPageTitle}
        eyebrow={copy.auth.reset.eyebrow}
        sheetCode={copy.auth.reset.sheetCode}
        art="compass"
      >
        <h1 className="heading text-3xl sm:text-5xl">{copy.auth.reset.tooManyTitle}</h1>
        <div className="mt-6">
          <ErrorBox>{copy.auth.reset.tooManyMessage}</ErrorBox>
        </div>
        <p className="mt-8 text-sm">
          <Link to="/login" className="link">
            {copy.auth.reset.backToLogin}
          </Link>
        </p>
      </AuthShell>
    );

  const type = show ? "text" : "password";
  return (
    <AuthShell
      title={copy.auth.reset.formPageTitle}
      eyebrow={copy.auth.reset.eyebrow}
      sheetCode={copy.auth.reset.sheetCode}
      art="compass"
    >
      <h1 className="heading text-3xl sm:text-5xl">{copy.auth.reset.formTitle}</h1>
      <p className="mt-3 text-subtle">{copy.auth.reset.formSubtitle}</p>
      <form onSubmit={submit} noValidate className="mt-8 flex flex-col gap-6">
        <Field
          label={copy.auth.reset.newPasswordLabel}
          id="new-password"
          type={type}
          autoComplete="new-password"
          required
          minLength={MIN}
          maxLength={256}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          hint={copy.auth.reset.minLengthHint(MIN)}
          autoFocus
        />
        <Field
          label={copy.auth.reset.confirmPasswordLabel}
          id="confirm-password"
          type={type}
          autoComplete="new-password"
          required
          minLength={MIN}
          maxLength={256}
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
        <label className="flex items-center gap-3 text-sm font-semibold text-ink">
          <input
            type="checkbox"
            checked={show}
            onChange={(e) => setShow(e.target.checked)}
            className="size-5 rounded-[2px] accent-[#2563eb]"
          />
          {copy.auth.reset.showPasswords}
        </label>
        {error && <ErrorBox>{error}</ErrorBox>}
        <Button type="submit" variant="primary" size="lg" disabled={busy} className="mt-2 w-full">
          {busy ? copy.auth.reset.submitting : copy.auth.reset.submit}
        </Button>
      </form>
    </AuthShell>
  );
}
