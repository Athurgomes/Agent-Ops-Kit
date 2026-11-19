import { Link } from "react-router-dom";
import { BRAND_DOT, BRAND_NAME } from "./brand";
import { copy } from "./copy";

export function Logo({
  to = "/",
  size = "text-2xl",
  inverted = false,
  className,
}: {
  to?: string | null;
  size?: string;
  inverted?: boolean;
  className?: string;
}) {
  const cls = [
    "font-display inline-flex items-baseline font-extrabold leading-none tracking-[-0.04em] no-underline",
    size,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const wordmark = (
    <>
      <span className={inverted ? "text-white" : "text-ink"}>{BRAND_NAME}</span>
      <span className="text-accent">{BRAND_DOT}</span>
    </>
  );

  if (to === null) {
    return <span className={cls}>{wordmark}</span>;
  }

  return (
    <Link to={to} className={cls} aria-label={copy.aria.brandHome}>
      {wordmark}
    </Link>
  );
}
