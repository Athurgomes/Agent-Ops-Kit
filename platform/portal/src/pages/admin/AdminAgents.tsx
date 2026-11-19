import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { adminApi } from "../../adminApi";
import { useCatalog } from "../../auth";
import { copy } from "../../copy";
import { Modal } from "../../dialogs";
import { fmtApiError, fmtDate } from "../../format";
import {
  Button,
  ErrorBox,
  Field,
  LogbookEmpty,
  LogbookLoading,
  PageHeader,
  Select,
  Tag,
  useAsync,
} from "../../ui";
import { indent, orderTree } from "./tree";

const SLUG = "[a-z0-9\\-]{1,64}";

function RegisterAgent({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const cat = useCatalog();
  const areas = useAsync(() => adminApi.areas(), []);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [area, setArea] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const a = await adminApi.createAgent({ area_id: Number(area), slug, name: name.trim() });
      cat.reload();
      onClose();
      nav(`/app/admin/agents/${a.id}`);
    } catch (err) {
      setError(fmtApiError(err));
      setBusy(false);
    }
  }

  return (
    <Modal title={copy.admin.agents.form.title} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-6">
        <p className="text-subtle">
          {copy.admin.agents.form.introPrefix}
          <code className="border border-ink bg-surface px-1.5 py-0.5 font-mono text-xs text-ink">
            platform.agent_id
          </code>
          {copy.admin.agents.form.introSuffix}
        </p>
        <Field
          label={copy.admin.agents.form.nameLabel}
          id="agent-name"
          required
          maxLength={200}
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <Field
          label={copy.admin.agents.form.slugLabel}
          id="agent-slug"
          required
          pattern={SLUG}
          maxLength={64}
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          hint={copy.admin.agents.form.slugHint}
        />
        <Select
          label={copy.admin.agents.form.areaLabel}
          id="agent-area"
          required
          value={area}
          onChange={(e) => setArea(e.target.value)}
        >
          <option value="">{copy.admin.agents.form.areaPlaceholder}</option>
          {areas.data &&
            orderTree(areas.data).map((a) => (
              <option key={a.id} value={a.id}>
                {indent(a.depth)}
                {a.name}
              </option>
            ))}
        </Select>
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3 border-t border-line pt-4">
          <Button onClick={onClose} disabled={busy}>
            {copy.common.cancel}
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !area}>
            {busy ? copy.admin.agents.form.submitting : copy.admin.agents.form.submit}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function AdminAgents() {
  const st = useAsync(() => adminApi.agents(), []);
  const [registering, setRegistering] = useState(false);

  useEffect(() => {
    document.title = `${copy.admin.agents.pageTitle} · ${copy.brand.full}`;
  }, []);

  const activeCount = st.data ? st.data.filter((a) => a.active).length : 0;

  return (
    <>
      <PageHeader
        crumbs={[{ label: copy.admin.crumbRoot }, { label: copy.admin.agents.crumb }]}
        title={copy.admin.agents.title}
        lead={copy.admin.agents.lead}
        stamp={copy.admin.agents.stamp}
      >
        <Button variant="primary" onClick={() => setRegistering(true)}>
          {copy.admin.agents.registerAction}
        </Button>
      </PageHeader>

      {st.loading && (
        <LogbookLoading label={copy.admin.agents.loadingLabel} caption={copy.admin.agents.loadingCaption} />
      )}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && st.data.length === 0 && (
        <LogbookEmpty
          tag={copy.admin.agents.emptyTag}
          title={copy.admin.agents.emptyTitle}
          artCaption={copy.admin.agents.emptyArtCaption}
        >
          {copy.admin.agents.emptyBody}
        </LogbookEmpty>
      )}
      {st.data && st.data.length > 0 && (
        <section aria-labelledby="admin-agents-list">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-4">
            <h2 id="admin-agents-list" className="eyebrow text-ink">
              {copy.admin.agents.listHeading}
            </h2>
            <span className="font-mono text-xs font-semibold tabular-nums text-subtle">
              {copy.admin.agents.countLabel(st.data.length, activeCount)}
            </span>
          </div>

          <div className="box overflow-x-auto">
            <table className="data-table min-w-[50rem]">
              <caption className="sr-only">{copy.admin.agents.tableCaption}</caption>
              <thead>
                <tr>
                  <th scope="col">{copy.admin.agents.columns.name}</th>
                  <th scope="col">{copy.admin.agents.columns.slug}</th>
                  <th scope="col">{copy.admin.agents.columns.area}</th>
                  <th scope="col">{copy.admin.agents.columns.status}</th>
                  <th scope="col">{copy.admin.agents.columns.activeTokens}</th>
                  <th scope="col">{copy.admin.agents.columns.lastReport}</th>
                </tr>
              </thead>
              <tbody>
                {st.data.map((a) => (
                  <tr key={a.id} className="hover:bg-surface">
                    <th scope="row">
                      <Link
                        to={`/app/admin/agents/${a.id}`}
                        className="font-display text-lg font-extrabold text-ink no-underline hover:text-accent"
                      >
                        {a.name}
                      </Link>
                    </th>
                    <td className="font-mono text-xs text-subtle">{a.slug}</td>
                    <td className="text-sm text-ink">{a.area_name}</td>
                    <td>
                      <Tag muted={!a.active}>{a.active ? copy.common.active : copy.common.inactive}</Tag>
                    </td>
                    <td className="font-mono text-sm tabular-nums text-ink">
                      {String(a.tokens_active_count).padStart(2, "0")}
                    </td>
                    <td className="whitespace-nowrap font-mono text-xs tabular-nums text-ink">
                      {a.last_report_at ? fmtDate(a.last_report_at) : copy.common.never}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      {registering && <RegisterAgent onClose={() => setRegistering(false)} />}
    </>
  );
}
