import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { BRAND } from "../brand";
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
      // erro genérico: não revela se o e-mail existe
      setError(err instanceof ApiError && err.status !== 401 ? err.message : "E-mail ou senha inválidos.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full items-center border-b-[3px] border-ink bg-pink">
      <div className="container-page grid w-full grid-cols-12 items-center gap-x-6 gap-y-12 py-24">
        <div className="col-span-12 flex flex-col gap-6 lg:col-span-6">
          <Title className="text-5xl lg:text-6xl">Entrar no {BRAND}</Title>
          <p className="max-w-md text-lg">
            Use o e-mail e a senha que a administração da sua organização criou. Se não tem acesso,
            peça a um administrador.
          </p>
        </div>
        <div className="col-span-12 lg:col-span-5 lg:col-start-8">
          <Card shadow>
            <form onSubmit={submit} className="flex flex-col gap-6">
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
              <Button type="submit" variant="primary" size="lg" disabled={busy}>
                {busy ? "Entrando…" : "Entrar"}
              </Button>
            </form>
          </Card>
        </div>
      </div>
    </div>
  );
}
