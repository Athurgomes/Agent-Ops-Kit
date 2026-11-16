import { LinkButton, Title } from "../ui";

export function NotFound() {
  return (
    <div className="container-page flex flex-col items-start gap-6 py-24">
      <Title>Página não encontrada</Title>
      <p>O endereço não existe ou mudou de lugar.</p>
      <LinkButton to="/" variant="secondary">
        Voltar ao início
      </LinkButton>
    </div>
  );
}
