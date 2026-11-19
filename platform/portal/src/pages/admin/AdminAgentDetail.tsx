import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useParams } from "react-router-dom";
import { adminApi } from "../../adminApi";
import type { AdminAgent, IssuedToken, TokenMeta } from "../../adminApi";
import { useCatalog } from "../../auth";
import { copy } from "../../copy";
import { ConfirmModal, Modal, OneTimeSecret } from "../../dialogs";
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

function EditAgent({ agent, onClose, onSaved }: { agent: AdminAgent; onClose: () => void; onSaved: () => void }) {
  const areas = useAsync(() => adminApi.areas(), []);
  const [name, setName] = useState(agent.name);
  const [area, setArea] = useState(String(agent.area_id));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: { name?: string; area_id?: number } = {};
      if (name.trim() !== agent.name) body.name = name.trim();
      if (Number(area) !== agent.area_id) body.area_id = Number(area);
      if (Object.keys(body).length) await adminApi.patchAgent(agent.id, body);
      onSaved();
      onClose();
    } catch (err) {
      setError(fmtApiError(err));
      setBusy(false);
    }
  }

  return (
    <Modal title={copy.admin.agentDetail.editForm.title} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-6">
        <Field
          label={copy.admin.agentDetail.editForm.nameLabel}
          id="edit-agent-name"
          required
          maxLength={200}
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <Select
          label={copy.admin.agentDetail.editForm.areaLabel}
          id="edit-agent-area"
          value={area}
          onChange={(e) => setArea(e.target.value)}
        >
          {areas.data &&
            orderTree(areas.data).map((a) => (
              <option key={a.id} value={a.id}>
                {indent(a.depth)}
                {a.name}
              </option>
            ))}
        </Select>
        <p className="text-sm text-subtle">{copy.admin.agentDetail.editForm.slugLockedHint}</p>
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3 border-t border-line pt-4">
          <Button onClick={onClose} disabled={busy}>
            {copy.common.cancel}
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
            {busy ? copy.common.saving : copy.common.saveChanges}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function TokenPanel({ agent, onChanged }: { agent: AdminAgent; onChanged: () => void }) {
  const [version, setVersion] = useState(0);
  const st = useAsync(() => adminApi.tokens(agent.id), [agent.id, version]);
  // The new token lives only in this state: it is dropped on dismiss or when leaving the page.
  const [issued, setIssued] = useState<IssuedToken | null>(null);
  const [issuing, setIssuing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<TokenMeta | null>(null);

  async function issue() {
    setIssuing(true);
    setError(null);
    try {
      setIssued(await adminApi.issueToken(agent.id));
      setVersion((v) => v + 1);
      onChanged();
    } catch (err) {
      setError(fmtApiError(err));
    } finally {
      setIssuing(false);
    }
  }

  const tCopy = copy.admin.agentDetail.tokens;

  return (
    <section aria-labelledby="tokens" className="mt-12">
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="eyebrow">{tCopy.eyebrow}</p>
          <h2 id="tokens" className="heading mt-1 text-2xl lg:text-3xl">
            {tCopy.heading}
          </h2>
          <p className="mt-2 max-w-2xl text-subtle">{tCopy.lead}</p>
        </div>
        <Button variant="primary" onClick={issue} disabled={issuing || !agent.active}>
          {issuing ? tCopy.issuing : tCopy.issueAction}
        </Button>
      </div>
      {!agent.active && (
        <p className="mb-5 border border-line bg-surface px-4 py-3 text-sm text-subtle">{tCopy.inactiveHint}</p>
      )}
      {error && (
        <div className="mb-5">
          <ErrorBox>{error}</ErrorBox>
        </div>
      )}

      {issued && (
        <div className="mb-6">
          <OneTimeSecret
            title={tCopy.secretTitle}
            announcement={tCopy.secretAnnouncement}
            secret={issued.token}
            onDismiss={() => setIssued(null)}
            extra={
              <div className="mt-6 border-t border-line pt-4 text-sm">
                <p className="mb-2 font-semibold text-ink">{tCopy.usageHeading}</p>
                <pre className="m-0 overflow-x-auto border border-ink bg-surface p-3 font-mono text-xs text-ink">
                  {`export AOK_PLATFORM_TOKEN="${issued.token}"
aok check --config agent.yaml --publish ${tCopy.usagePlatformPlaceholder} --agent-id ${agent.slug}`}
                </pre>
              </div>
            }
          />
        </div>
      )}

      {st.loading && !st.data && (
        <LogbookLoading label={tCopy.loadingLabel} caption={tCopy.loadingCaption} />
      )}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && st.data.length === 0 && (
        <LogbookEmpty tag={tCopy.emptyTag} title={tCopy.emptyTitle} artCaption={tCopy.emptyArtCaption}>
          {tCopy.emptyBody}
        </LogbookEmpty>
      )}
      {st.data && st.data.length > 0 && (
        <div className="box hidden overflow-x-auto md:block">
          <table className="data-table min-w-[34rem]">
            <caption className="sr-only">{tCopy.tableCaption(agent.name)}</caption>
            <thead>
              <tr>
                <th scope="col">{tCopy.columns.token}</th>
                <th scope="col">{tCopy.columns.createdAt}</th>
                <th scope="col">{tCopy.columns.lastUsedAt}</th>
                <th scope="col">{tCopy.columns.status}</th>
                <th scope="col" className="text-right">
                  <span className="sr-only">{tCopy.columns.actions}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {st.data.map((t) => (
                <tr key={t.token_id} className="hover:bg-surface">
                  <th scope="row" className="font-mono text-xs font-semibold text-ink">
                    #{t.token_id}
                  </th>
                  <td className="whitespace-nowrap font-mono text-xs tabular-nums text-ink">
                    {fmtDate(t.created_at)}
                  </td>
                  <td className="whitespace-nowrap font-mono text-xs tabular-nums text-subtle">
                    {t.last_used_at ? fmtDate(t.last_used_at) : copy.common.never}
                  </td>
                  <td>
                    {t.revoked_at ? (
                      <Tag muted>{tCopy.revokedAt(fmtDate(t.revoked_at))}</Tag>
                    ) : (
                      <Tag>{copy.common.active}</Tag>
                    )}
                  </td>
                  <td className="text-right">
                    {!t.revoked_at && (
                      <Button size="sm" onClick={() => setRevoking(t)} aria-label={tCopy.revokeAria(t.token_id)}>
                        {tCopy.revokeAction}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {st.data && st.data.length > 0 && (
        <div className="border border-ink bg-paper md:hidden">
          <div className="ruler-x" aria-hidden="true" />
          <ul className="m-0 list-none divide-y divide-ink/25 p-0">
            {st.data.map((t) => (
              <li key={t.token_id} className="flex flex-col gap-2.5 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-sm font-semibold text-ink">{tCopy.tokenRef(t.token_id)}</span>
                  {t.revoked_at ? (
                    <Tag muted>{tCopy.revokedAt(fmtDate(t.revoked_at))}</Tag>
                  ) : (
                    <Tag>{copy.common.active}</Tag>
                  )}
                </div>
                <p className="font-mono text-xs text-subtle">
                  {tCopy.mobileMeta(fmtDate(t.created_at), t.last_used_at ? fmtDate(t.last_used_at) : copy.common.never)}
                </p>
                {!t.revoked_at && (
                  <div className="pt-1">
                    <Button size="sm" onClick={() => setRevoking(t)} aria-label={tCopy.revokeAria(t.token_id)}>
                      {tCopy.revokeAction}
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {revoking && (
        <ConfirmModal
          title={tCopy.revokeModalTitle(revoking.token_id)}
          confirmLabel={tCopy.revokeModalConfirm}
          onClose={() => setRevoking(null)}
          onConfirm={async () => {
            await adminApi.revokeToken(agent.id, revoking.token_id);
            setVersion((v) => v + 1);
            onChanged();
          }}
        >
          <p>{tCopy.revokeModalBody}</p>
        </ConfirmModal>
      )}
    </section>
  );
}

export function AdminAgentDetail() {
  const { agentId } = useParams();
  const id = Number(agentId);
  const cat = useCatalog();
  const [version, setVersion] = useState(0);
  const st = useAsync(() => adminApi.agents(), [version]);
  const agent = st.data?.find((a) => a.id === id);
  const [editing, setEditing] = useState(false);
  const [toggling, setToggling] = useState(false);
  const reload = () => {
    setVersion((v) => v + 1);
    cat.reload();
  };

  useEffect(() => {
    document.title = `${copy.admin.agentDetail.pageTitle(agent?.name)} · ${copy.brand.full}`;
  }, [agent?.name]);

  return (
    <>
      <PageHeader
        crumbs={[
          { label: copy.admin.crumbRoot },
          { label: copy.admin.agents.crumb, to: "/app/admin/agents" },
          { label: agent?.name ?? copy.admin.agentDetail.fallbackTitle },
        ]}
        title={agent?.name ?? copy.admin.agentDetail.fallbackTitle}
        stamp={copy.admin.agentDetail.stamp}
      >
        {agent && (
          <div className="flex flex-wrap gap-3">
            <Button onClick={() => setEditing(true)}>{copy.common.edit}</Button>
            <Button onClick={() => setToggling(true)}>
              {agent.active ? copy.common.deactivate : copy.common.activate}
            </Button>
          </div>
        )}
      </PageHeader>

      {st.loading && !st.data && (
        <LogbookLoading
          label={copy.admin.agentDetail.loadingLabel}
          caption={copy.admin.agentDetail.loadingCaption}
        />
      )}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && !agent && (
        <LogbookEmpty
          tag={copy.admin.agentDetail.notFoundTag}
          title={copy.admin.agentDetail.notFoundTitle}
          artCaption={copy.admin.agentDetail.notFoundArtCaption}
        >
          {copy.admin.agentDetail.notFoundBody}
        </LogbookEmpty>
      )}
      {agent && (
        <>
          <section aria-labelledby="agent-meta" className="border border-ink bg-paper">
            <div className="ruler-x" aria-hidden="true" />
            <div className="border-b border-line bg-surface px-5 py-2.5">
              <h2 id="agent-meta" className="eyebrow text-ink">
                {copy.admin.agentDetail.metaHeading}
              </h2>
            </div>
            <dl className="m-0 grid grid-cols-1 divide-y divide-line sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4">
              <div className="p-5 sm:border-b sm:border-r sm:border-line lg:border-b-0">
                <dt className="eyebrow">{copy.admin.agentDetail.meta.slug}</dt>
                <dd className="mt-1.5 break-all font-mono text-sm font-semibold text-ink">{agent.slug}</dd>
              </div>
              <div className="p-5 sm:border-b sm:border-line lg:border-b-0 lg:border-r">
                <dt className="eyebrow">{copy.admin.agentDetail.meta.area}</dt>
                <dd className="mt-1.5 font-semibold text-ink">{agent.area_name}</dd>
              </div>
              <div className="p-5 sm:border-r sm:border-line">
                <dt className="eyebrow">{copy.admin.agentDetail.meta.status}</dt>
                <dd className="mt-1.5">
                  <Tag muted={!agent.active}>{agent.active ? copy.common.active : copy.common.inactive}</Tag>
                </dd>
              </div>
              <div className="p-5">
                <dt className="eyebrow">{copy.admin.agentDetail.meta.lastReport}</dt>
                <dd className="mt-1.5 font-mono text-sm font-semibold tabular-nums text-ink">
                  {agent.last_report_at ? fmtDate(agent.last_report_at) : copy.common.never}
                </dd>
              </div>
            </dl>
          </section>
          <TokenPanel agent={agent} onChanged={() => setVersion((v) => v + 1)} />
        </>
      )}

      {agent && editing && <EditAgent agent={agent} onClose={() => setEditing(false)} onSaved={reload} />}
      {agent && toggling && (
        <ConfirmModal
          title={
            agent.active
              ? copy.admin.agentDetail.toggle.deactivateTitle(agent.name)
              : copy.admin.agentDetail.toggle.activateTitle(agent.name)
          }
          confirmLabel={agent.active ? copy.common.deactivate : copy.common.activate}
          onClose={() => setToggling(false)}
          onConfirm={async () => {
            await adminApi.patchAgent(agent.id, { active: !agent.active });
            reload();
          }}
        >
          <p>
            {agent.active
              ? copy.admin.agentDetail.toggle.deactivateBody
              : copy.admin.agentDetail.toggle.activateBody}
          </p>
        </ConfirmModal>
      )}
    </>
  );
}
