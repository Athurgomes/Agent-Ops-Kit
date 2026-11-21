import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { copy } from "../../copy";
import { ConfirmModal, Modal } from "../../dialogs";
import { fmtApiError, fmtDate } from "../../format";
import { opsApi } from "../../opsApi";
import type { OpsOrg } from "../../opsApi";
import {
  Button,
  ErrorBox,
  Field,
  LogbookEmpty,
  LogbookLoading,
  PageHeader,
  Tag,
  useAsync,
} from "../../ui";

const SLUG = "[a-z0-9\\-]{1,64}";

/** Confirmation that spells out what deactivating (or reactivating) an organization does. */
export function ToggleOrg({
  org,
  onClose,
  onDone,
}: {
  org: { id: number; name: string; active: boolean };
  onClose: () => void;
  onDone: () => void;
}) {
  const tCopy = copy.ops.orgs.toggleModal;
  return (
    <ConfirmModal
      title={org.active ? tCopy.deactivateTitle(org.name) : tCopy.activateTitle(org.name)}
      confirmLabel={org.active ? copy.common.deactivate : copy.common.activate}
      onClose={onClose}
      onConfirm={async () => {
        await opsApi.patchOrg(org.id, { active: !org.active });
        onDone();
      }}
    >
      <p>{org.active ? tCopy.deactivateBody : tCopy.activateBody}</p>
    </ConfirmModal>
  );
}

function CreateOrg({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fCopy = copy.ops.orgs.createForm;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const o = await opsApi.createOrg(slug, name.trim());
      onClose();
      nav(`/ops/organizations/${o.id}`);
    } catch (err) {
      setError(fmtApiError(err));
      setBusy(false);
    }
  }

  return (
    <Modal title={fCopy.title} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-6">
        <Field
          label={fCopy.nameLabel}
          id="org-name"
          required
          maxLength={200}
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <Field
          label={fCopy.slugLabel}
          id="org-slug"
          required
          pattern={SLUG}
          maxLength={64}
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          hint={fCopy.slugHint}
          errorId={error === copy.opsErrors.orgSlugInUse ? "org-slug-error" : undefined}
        />
        {error && <ErrorBox id="org-slug-error">{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3 border-t border-line pt-4">
          <Button onClick={onClose} disabled={busy}>
            {copy.common.cancel}
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
            {busy ? fCopy.submitting : fCopy.submit}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function OpsOrganizations() {
  const [version, setVersion] = useState(0);
  const st = useAsync(() => opsApi.orgs(), [version]);
  const [creating, setCreating] = useState(false);
  const [toggling, setToggling] = useState<OpsOrg | null>(null);

  const oCopy = copy.ops.orgs;

  useEffect(() => {
    document.title = `${oCopy.pageTitle} · ${copy.opsBar.subtitle} · ${copy.brand.full}`;
  }, [oCopy.pageTitle]);

  const orgs = st.data ?? [];
  const totalActive = orgs.filter((o) => o.active).length;
  const totalAgents = orgs.reduce((sum, o) => sum + o.agents_count, 0);
  const totalReports = orgs.reduce((sum, o) => sum + o.reports_count, 0);

  return (
    <>
      <PageHeader
        crumbs={[{ label: copy.opsBar.subtitle }, { label: oCopy.crumb }]}
        title={oCopy.title}
        lead={oCopy.lead}
        stamp={oCopy.stamp}
      >
        <Button variant="primary" onClick={() => setCreating(true)}>
          {oCopy.createAction}
        </Button>
      </PageHeader>

      {st.loading && !st.data && <LogbookLoading label={oCopy.loadingLabel} caption={oCopy.loadingCaption} />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && st.data.length === 0 && (
        <LogbookEmpty tag={oCopy.emptyTag} title={oCopy.emptyTitle} artCaption={oCopy.emptyArtCaption}>
          {oCopy.emptyBody}
        </LogbookEmpty>
      )}
      {st.data && st.data.length > 0 && (
        <>
          <dl className="mb-10 grid grid-cols-2 border border-ink bg-paper sm:grid-cols-4">
            {[
              [oCopy.kpi.orgs, orgs.length],
              [oCopy.kpi.active, totalActive],
              [oCopy.kpi.agents, totalAgents],
              [oCopy.kpi.reports, totalReports],
            ].map(([label, val], i) => (
              <div
                key={String(label)}
                className={`p-5 ${i < 2 ? "border-b border-line sm:border-b-0" : ""} ${i % 2 === 0 ? "border-r border-line" : ""} ${i === 1 ? "sm:border-r sm:border-line" : ""}`}
              >
                <dt className="eyebrow">{label}</dt>
                <dd className="mt-2 font-display text-3xl font-extrabold tabular-nums text-ink">
                  {String(val).padStart(2, "0")}
                </dd>
              </div>
            ))}
          </dl>

          <section aria-labelledby="ops-orgs-list">
            <div className="mb-4 flex flex-wrap items-baseline justify-between gap-4">
              <h2 id="ops-orgs-list" className="eyebrow text-ink">
                {oCopy.listHeading}
              </h2>
              <span className="font-mono text-xs font-semibold tabular-nums text-subtle">
                {oCopy.countLabel(st.data.length)}
              </span>
            </div>

            <div className="box overflow-x-auto">
              <table className="data-table [&_td]:px-2 [&_th]:px-2 [&_tr>*:first-child]:pl-4 [&_tr>*:last-child]:pr-4">
                <caption className="sr-only">{oCopy.tableCaption}</caption>
                <thead>
                  <tr>
                    <th scope="col" className="min-w-[10rem]">
                      {oCopy.columns.name}
                    </th>
                    <th scope="col">{oCopy.columns.slug}</th>
                    <th scope="col">{oCopy.columns.status}</th>
                    <th scope="col">{oCopy.columns.areas}</th>
                    <th scope="col">{oCopy.columns.agents}</th>
                    <th scope="col">{oCopy.columns.users}</th>
                    <th scope="col">{oCopy.columns.activeTokens}</th>
                    <th scope="col">{oCopy.columns.reports}</th>
                    <th scope="col">{oCopy.columns.lastReport}</th>
                    <th scope="col" className="text-right">
                      <span className="sr-only">{oCopy.columns.actions}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {st.data.map((o) => (
                    <tr key={o.id} className="hover:bg-surface">
                      <th scope="row" className="min-w-[10rem]">
                        <Link
                          to={`/ops/organizations/${o.id}`}
                          className="font-display text-base font-extrabold leading-snug text-ink no-underline hover:text-accent"
                        >
                          {o.name}
                        </Link>
                      </th>
                      <td className="whitespace-nowrap font-mono text-xs text-subtle">{o.slug}</td>
                      <td className="whitespace-nowrap">
                        <Tag muted={!o.active}>
                          {o.active ? copy.common.activeFem : copy.common.inactiveFem}
                        </Tag>
                      </td>
                      <td className="font-mono text-sm tabular-nums text-ink">
                        {String(o.areas_count).padStart(2, "0")}
                      </td>
                      <td className="font-mono text-sm tabular-nums text-ink">
                        {String(o.agents_count).padStart(2, "0")}
                      </td>
                      <td className="font-mono text-sm tabular-nums text-ink">
                        {String(o.users_count).padStart(2, "0")}
                      </td>
                      <td className="font-mono text-sm tabular-nums text-ink">
                        {String(o.tokens_active_count).padStart(2, "0")}
                      </td>
                      <td className="font-mono text-sm tabular-nums text-ink">
                        {String(o.reports_count).padStart(2, "0")}
                      </td>
                      <td className="whitespace-nowrap font-mono text-xs tabular-nums text-ink">
                        {o.last_report_at ? fmtDate(o.last_report_at) : copy.common.never}
                      </td>
                      <td className="whitespace-nowrap text-right">
                        <Button
                          size="sm"
                          onClick={() => setToggling(o)}
                          aria-label={oCopy.toggleAria(o.active, o.name)}
                        >
                          {o.active ? copy.common.deactivate : copy.common.activate}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
      {creating && <CreateOrg onClose={() => setCreating(false)} />}
      {toggling && (
        <ToggleOrg org={toggling} onClose={() => setToggling(null)} onDone={() => setVersion((v) => v + 1)} />
      )}
    </>
  );
}
