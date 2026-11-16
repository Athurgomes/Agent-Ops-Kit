import { LinkButton, Title } from "../ui";

export function NotFound() {
  return (
    <div className="container-page flex flex-col items-start gap-6 py-24">
      <Title>Page not found</Title>
      <p className="text-subtle">The address does not exist or has moved.</p>
      <LinkButton to="/">Back to home</LinkButton>
    </div>
  );
}
