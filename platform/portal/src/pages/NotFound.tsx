import { LinkButton, Title } from "../ui";

export function NotFound() {
  return (
    <div className="flex flex-col items-start gap-4">
      <Title>Página não encontrada</Title>
      <LinkButton to="/" tone="yellow">
        Voltar ao início
      </LinkButton>
    </div>
  );
}
