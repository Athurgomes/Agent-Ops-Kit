import { useEffect } from "react";
import type { ReactNode } from "react";
import { BRAND } from "../brand";
import { Logo } from "../ui";

/** Same look as the login page (wordmark on top, square card), for the password recovery pages. */
export function AuthShell({ title, children }: { title: string; children: ReactNode }) {
  useEffect(() => {
    const before = document.title;
    document.title = `${title} · ${BRAND}`;
    return () => {
      document.title = before;
    };
  }, [title]);
  return (
    <main id="content" className="flex min-h-screen flex-col items-center px-6 py-12">
      <Logo size="text-4xl" />
      <div className="box mt-12 w-full max-w-md p-8 sm:p-12">{children}</div>
    </main>
  );
}
