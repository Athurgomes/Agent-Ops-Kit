// Native <dialog> modals (focus is trapped by the browser; we restore focus on close), a confirm
// dialog, a copy button and a one-time secret block. No storage: secrets live only in React state.
import { useEffect, useId, useRef, useState } from "react";
import type { ReactNode } from "react";
import { copy } from "./copy";
import { fmtApiError } from "./format";
import { Button, ErrorBox, cx } from "./ui";

export function Modal({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    if (ref.current && !ref.current.open) ref.current.showModal();
    return () => {
      if (opener?.isConnected) opener.focus(); // give focus back to what opened it
    };
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby={id}
      onClose={onClose}
      className={cx(
        "box m-auto w-[calc(100%-32px)] p-0 text-ink backdrop:bg-ink/55",
        wide ? "max-w-2xl" : "max-w-lg",
      )}
    >
      <div className="border-b border-ink bg-surface px-6 py-4 sm:px-8">
        <h2 id={id} className="heading text-2xl">
          {title}
        </h2>
        <div aria-hidden="true" className="ruler-x mt-3" />
      </div>
      <div className="p-6 sm:p-8">{children}</div>
    </dialog>
  );
}

/** Confirmation with a clear consequence; errors from onConfirm are shown inside the dialog. */
export function ConfirmModal({
  title,
  children,
  confirmLabel,
  onConfirm,
  onClose,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <Modal title={title} onClose={onClose}>
      <div className="flex flex-col gap-6">
        <div className="text-subtle">{children}</div>
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3">
          <Button onClick={onClose} disabled={busy} autoFocus>
            {copy.common.cancel}
          </Button>
          <Button
            variant="dark"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await onConfirm();
                onClose();
              } catch (e) {
                setError(fmtApiError(e));
                setBusy(false);
              }
            }}
          >
            {busy ? copy.common.working : confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  );
}

export function CopyButton({ text, label = copy.common.copy }: { text: string; label?: string }) {
  const [state, setState] = useState<"idle" | "ok" | "fail">("idle");
  return (
    <span className="inline-flex items-center gap-3">
      <Button
        size="sm"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text);
            setState("ok");
          } catch {
            setState("fail"); // e.g. clipboard blocked: the value is selectable on screen
          }
        }}
      >
        {label}
      </Button>
      <span role="status" className="text-sm text-subtle">
        {state === "ok" && copy.common.copied}
        {state === "fail" && copy.common.copyFailed}
      </span>
    </span>
  );
}

/** Shown once: the parent keeps the secret only in state and drops it when dismissed or unmounted.
 *  Not a live region (a screen reader would read the secret aloud); focus moves to the block and a
 *  generic, secret-free message is announced instead. */
export function OneTimeSecret({
  title,
  secret,
  extra,
  announcement = copy.dialogs.secretAnnouncement,
  onDismiss,
}: {
  title: string;
  secret: string;
  extra?: ReactNode;
  announcement?: string;
  onDismiss: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [said, setSaid] = useState("");
  useEffect(() => {
    ref.current?.focus();
    setSaid(announcement); // filled after mount so the status region is announced
  }, [announcement]);
  return (
    <div ref={ref} role="region" aria-label={title} tabIndex={-1} className="box border-l-4 border-l-accent">
      <p role="status" className="sr-only">
        {said}
      </p>
      <div className="border-b border-ink bg-surface px-6 py-3.5">
        <p className="heading text-xl">{title}</p>
        <div aria-hidden="true" className="ruler-x mt-2.5" />
      </div>
      <div className="p-6">
        <p className="font-semibold text-ink">{copy.dialogs.secretWarning}</p>
        <p className="mt-4 break-all border border-ink bg-surface p-3 font-mono text-sm text-ink select-all">
          {secret}
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-4">
          <CopyButton text={secret} />
          <Button size="sm" variant="primary" onClick={onDismiss}>
            {copy.dialogs.secretStored}
          </Button>
        </div>
        {extra}
      </div>
    </div>
  );
}
