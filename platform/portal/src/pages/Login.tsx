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

  if (!loading && me) return <Navigate to={from?.startsWith("/app") ? from : "/app"} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email.trim(), password);
      nav(from?.startsWith("/app") ? from : "/app", { replace: true });
    } catch (err) {
      // erro genérico: não revela se o e-mail existe
      setError(
        err instanceof ApiError && err.status !== 401 ? err.message : "E-mail ou senha inválidos.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-lg flex-col gap-6">
      <Title>Entrar</Title>
      <Card tone="pink">
        <form onSubmit={submit} className="flex flex-col gap-5">
          <Field
            label="E-mail"
            id="email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Field
            label="Senha"
            id="senha"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && <ErrorBox>{error}</ErrorBox>}
          <Button type="submit" disabled={busy}>
            {busy ? "Entrando…" : "Entrar"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
