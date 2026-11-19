import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useParams } from "react-router-dom";
import { copy } from "../../copy";
import { ConfirmModal, Modal, OneTimeSecret } from "../../dialogs";
import { fmtApiError, fmtDate } from "../../format";
import { opsApi } from "../../opsApi";
import type { OpsAreaNode, OpsDetail, OpsUser } from "../../opsApi";
import {
  Button,
  ErrorBox,
  Field,
  LogbookEmpty,
  LogbookLoading,
  PageHeader,
  SemaforoBadge,
  Tag,
  useAsync,
} from "../../ui";
import { ACTIONS, TARGETS } from "../admin/AdminActivity";
import { ToggleOrg } from "./OpsOrganizations";

type Secret = { title: string; value: string };

function countAreas(nodes: OpsAreaNode[]): number {
  return nodes.reduce((sum, n) => sum + 1 + countAreas(n.children), 0);
}

function CreateAdmin({ orgId, onClose, onDone }: { orgId: number; onClose: () => void; onDone: (s: Secret) => void }) {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fCopy = copy.ops.orgDetail.createAdminForm;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await opsApi.createAdmin(orgId, email.trim());
      onDone({ title: copy.admin.users.initialPasswordTitle(r.email), value: r.password });
      onClose();
    } catch (err) {
      setError(fmtApiError(err));
      setBusy(false);
    }
  }

  return (
    <Modal title={fCopy.title} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-6">
        <p className="text-subtle">{fCopy.lead}</p>
        <Field
          label={fCopy.emailLabel}
          id="admin-email"
          type="email"
          required
          maxLength={254}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoFocus
        />
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3 border-t border-line pt-4">
          <Button onClick={onClose} disabled={busy}>
            {copy.common.cancel}
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !email.trim()}>
            {busy ? fCopy.submitting : fCopy.submit}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function Tree({ nodes, depth = 0 }: { nodes: OpsAreaNode[]; depth?: number }) {
  return (
    <ul className="m-0 list-none p-0">
      {nodes.map((n) => (
        <li key={n.id} className="py-1.5">
          <div className="flex items-center gap-2">
            {depth > 0 && (
              <span aria-hidden="true" className="font-mono text-xs text-subtle">
                ├──
              </span>
            )}
            <span className={depth === 0 ? "font-display text-lg font-extrabold text-ink" : "font-semibold text-ink"}>
              {n.name}
            </span>
          </div>
          {n.children.length > 0 && (
            <div className="ml-3 mt-1 border-l border-ink/30 pl-4">
              <Tree nodes={n.children} depth={depth + 1} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

const roleText = (a: { role: string; area_name: string | null }) =>
  a.role === "org_admin"
    ? copy.admin.roles.orgAdmin
    : copy.admin.roles.viewerTag(a.area_name ?? copy.admin.roles.areaFallback);

function Events({ orgId }: { orgId: number }) {
  const PAGE = 20;
  const [offset, setOffset] = useState(0);
  const st = useAsync(() => opsApi.orgEvents(orgId, PAGE, offset), [orgId, offset]);
  const rows = st.data ?? [];
  const eCopy = copy.ops.orgDetail.events;
  const aCopy = copy.admin.activity;
  const page = offset / PAGE + 1;

  return (
    <section aria-labelledby="org-events" className="mt-12">
      <p className="eyebrow">{eCopy.eyebrow}</p>
      <h2 id="org-events" className="heading mt-1 text-2xl lg:text-3xl">
        {eCopy.heading}
      </h2>
      <p className="mb-5 mt-2 max-w-2xl text-subtle">{eCopy.lead}</p>
      {st.loading && !st.data && <LogbookLoading label={aCopy.loadingLabel} caption={aCopy.loadingCaption} />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && rows.length === 0 && (
        <LogbookEmpty
          tag={aCopy.emptyTag}
          title={offset ? aCopy.emptyMoreTitle : aCopy.emptyTitle}
          artCaption={aCopy.emptyArtCaption}
        >
          {offset ? aCopy.emptyMoreBody : aCopy.emptyBody}
        </LogbookEmpty>
      )}
      {rows.length > 0 && (
        <div className="box overflow-x-auto">
          <table className="data-table min-w-[36rem]">
            <caption className="sr-only">{eCopy.tableCaption}</caption>
            <thead>
              <tr>
                <th scope="col">{aCopy.columns.when}</th>
                <th scope="col">{aCopy.columns.who}</th>
                <th scope="col">{aCopy.columns.action}</th>
                <th scope="col">{aCopy.columns.target}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} className="hover:bg-surface">
                  <td className="whitespace-nowrap font-mono text-xs tabular-nums text-ink">{fmtDate(e.at)}</td>
                  <td className="break-all font-mono text-xs text-ink">
                    {e.actor_email ?? aCopy.bootstrapKey}
                  </td>
                  <td className="font-semibold text-ink">{ACTIONS[e.action] ?? e.action}</td>
                  <td className="text-sm text-ink">
                    {TARGETS[e.target_type] ?? e.target_type}
                    {e.target_id !== null && (
                      <span className="font-mono text-xs text-subtle"> #{e.target_id}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <nav
        aria-label={eCopy.paginationAria}
        className="mt-5 flex flex-wrap items-center gap-4 border-t border-line pt-4"
      >
        <Button size="sm" disabled={offset === 0 || st.loading} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          {copy.common.newer}
        </Button>
        <span className="font-mono text-xs font-semibold tabular-nums text-subtle">
          {copy.common.pageLabel(page)}
        </span>
        <Button size="sm" disabled={rows.length < PAGE || st.loading} onClick={() => setOffset(offset + PAGE)}>
          {copy.common.older}
        </Button>
      </nav>
    </section>
  );
}

export function OpsOrgDetail() {
  const { orgId } = useParams();
  const id = Number(orgId);
  const [version, setVersion] = useState(0);
  const st = useAsync(() => opsApi.org(id), [id, version]);
  const org: OpsDetail | null = st.data;
  // One-time secrets (generated passwords) live only in this state; dismissing or leaving drops them.
  const [secret, setSecret] = useState<Secret | null>(null);
  const [creating, setCreating] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [resetting, setResetting] = useState<OpsUser | null>(null);
  const reload = () => setVersion((v) => v + 1);

  const dCopy = copy.ops.orgDetail;

  useEffect(() => {
    document.title = `${dCopy.pageTitle(org?.name)} · ${copy.opsBar.subtitle} · ${copy.brand.full}`;
  }, [dCopy, org?.name]);

  const resetButton = (u: OpsUser) =>
    u.access.some((a) => a.role === "org_admin") && (
      <Button size="sm" onClick={() => setResetting(u)} aria-label={dCopy.users.resetAria(u.email)}>
        {dCopy.users.resetAction}
      </Button>
    );

  return (
    <>
      <PageHeader
        crumbs={[
          { label: copy.opsBar.subtitle },
          { label: copy.ops.orgs.crumb, to: "/ops/organizations" },
          { label: org?.name ?? dCopy.fallbackTitle },
        ]}
        title={org?.name ?? dCopy.fallbackTitle}
        stamp={dCopy.stamp}
        lead={
          org ? (
            <span className="font-mono text-xs font-semibold uppercase tracking-[0.06em] text-subtle">
              {dCopy.slugPrefix}
              <span className="normal-case text-ink">{org.slug}</span>
            </span>
          ) : undefined
        }
      >
        {org && (
          <div className="flex flex-wrap gap-3">
            <Button variant="primary" onClick={() => setCreating(true)}>
              {dCopy.createAdminAction}
            </Button>
            <Button onClick={() => setToggling(true)}>
              {org.active ? copy.common.deactivate : copy.common.activate}
            </Button>
          </div>
        )}
      </PageHeader>

      <section
        aria-labelledby="ops-metadata-scope"
        className="mb-10 border border-ink border-l-4 border-l-accent bg-surface"
      >
        <div className="border-b border-line px-5 py-2.5">
          <h2 id="ops-metadata-scope" className="eyebrow text-ink">
            {dCopy.metadataBannerEyebrow}
          </h2>
        </div>
        <p className="px-5 py-4 text-sm font-semibold text-ink">{dCopy.metadataBannerBody}</p>
      </section>

      {secret && (
        <div className="mb-10">
          <OneTimeSecret
            title={secret.title}
            announcement={copy.admin.users.secretAnnouncement}
            secret={secret.value}
            onDismiss={() => setSecret(null)}
            extra={<p className="mt-4 border-t border-line pt-4 text-sm text-subtle">{dCopy.secureChannelNote}</p>}
          />
        </div>
      )}

      {st.loading && !org && <LogbookLoading label={dCopy.loadingLabel} caption={dCopy.loadingCaption} />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {org && (
        <>
          <div className="mb-12 border border-ink bg-paper">
            <div className="ruler-x" aria-hidden="true" />
            <dl className="m-0 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
              <div className="border-b border-r border-line p-4 lg:border-b-0">
                <dt className="eyebrow">{dCopy.meta.status}</dt>
                <dd className="mt-1.5">
                  <Tag muted={!org.active}>
                    {org.active ? copy.common.activeFem : copy.common.inactiveFem}
                  </Tag>
                </dd>
              </div>
              <div className="border-b border-line p-4 sm:border-r lg:border-b-0">
                <dt className="eyebrow">{dCopy.meta.createdAt}</dt>
                <dd className="mt-1.5 font-mono text-xs font-semibold tabular-nums text-ink">
                  {fmtDate(org.created_at)}
                </dd>
              </div>
              <div className="border-b border-r border-line p-4 sm:border-r-0 lg:border-b-0 lg:border-r">
                <dt className="eyebrow">{dCopy.meta.areas}</dt>
                <dd className="mt-1.5 font-mono text-sm font-semibold tabular-nums text-ink">
                  {String(countAreas(org.areas)).padStart(2, "0")}
                </dd>
              </div>
              <div className="border-b border-line p-4 sm:border-b-0 sm:border-r">
                <dt className="eyebrow">{dCopy.meta.agents}</dt>
                <dd className="mt-1.5 font-mono text-sm font-semibold tabular-nums text-ink">
                  {String(org.agents.length).padStart(2, "0")}
                </dd>
              </div>
              <div className="border-r border-line p-4">
                <dt className="eyebrow">{dCopy.meta.users}</dt>
                <dd className="mt-1.5 font-mono text-sm font-semibold tabular-nums text-ink">
                  {String(org.users.length).padStart(2, "0")}
                </dd>
              </div>
              <div className="p-4">
                <dt className="eyebrow">{dCopy.meta.reports}</dt>
                <dd className="mt-1.5 font-mono text-sm font-semibold tabular-nums text-ink">
                  {String(org.reports.length).padStart(2, "0")}
                </dd>
              </div>
            </dl>
          </div>

          <section aria-labelledby="o-areas">
            <p className="eyebrow">{dCopy.areas.eyebrow}</p>
            <h2 id="o-areas" className="heading mb-4 mt-1 text-2xl lg:text-3xl">
              {dCopy.areas.heading}
            </h2>
            {org.areas.length === 0 ? (
              <LogbookEmpty
                tag={dCopy.areas.emptyTag}
                title={dCopy.areas.emptyTitle}
                artCaption={dCopy.areas.emptyArtCaption}
              />
            ) : (
              <div className="box p-5">
                <Tree nodes={org.areas} />
              </div>
            )}
          </section>

          <section aria-labelledby="o-agents" className="mt-12">
            <p className="eyebrow">{dCopy.agents.eyebrow}</p>
            <h2 id="o-agents" className="heading mb-4 mt-1 text-2xl lg:text-3xl">
              {dCopy.agents.heading}
            </h2>
            {org.agents.length === 0 ? (
              <LogbookEmpty
                tag={dCopy.agents.emptyTag}
                title={dCopy.agents.emptyTitle}
                artCaption={dCopy.agents.emptyArtCaption}
              />
            ) : (
              <div className="box overflow-x-auto">
                <table className="data-table min-w-[48rem]">
                  <caption className="sr-only">{dCopy.agents.tableCaption}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{dCopy.agents.columns.name}</th>
                      <th scope="col">{dCopy.agents.columns.slug}</th>
                      <th scope="col">{dCopy.agents.columns.area}</th>
                      <th scope="col">{dCopy.agents.columns.status}</th>
                      <th scope="col">{dCopy.agents.columns.activeTokens}</th>
                      <th scope="col">{dCopy.agents.columns.latestSemaforo}</th>
                      <th scope="col">{dCopy.agents.columns.lastReport}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {org.agents.map((a) => (
                      <tr key={a.id} className="hover:bg-surface">
                        <th scope="row" className="font-semibold text-ink">
                          {a.name}
                        </th>
                        <td className="font-mono text-xs text-subtle">{a.slug}</td>
                        <td className="text-sm text-ink">{a.area_name}</td>
                        <td>
                          <Tag muted={!a.active}>{a.active ? copy.common.active : copy.common.inactive}</Tag>
                        </td>
                        <td className="font-mono text-sm tabular-nums text-ink">
                          {String(a.tokens_active_count).padStart(2, "0")}
                        </td>
                        <td>
                          {a.latest_semaforo ? (
                            <SemaforoBadge value={a.latest_semaforo} />
                          ) : (
                            <span className="text-sm text-subtle">{dCopy.agents.noReport}</span>
                          )}
                        </td>
                        <td className="whitespace-nowrap font-mono text-xs tabular-nums text-ink">
                          {a.last_report_at ? fmtDate(a.last_report_at) : copy.common.never}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section aria-labelledby="o-users" className="mt-12">
            <p className="eyebrow">{dCopy.users.eyebrow}</p>
            <h2 id="o-users" className="heading mb-4 mt-1 text-2xl lg:text-3xl">
              {dCopy.users.heading}
            </h2>
            {org.users.length === 0 ? (
              <LogbookEmpty
                tag={dCopy.users.emptyTag}
                title={dCopy.users.emptyTitle}
                artCaption={dCopy.users.emptyArtCaption}
              >
                {dCopy.users.emptyBody}
              </LogbookEmpty>
            ) : (
              <>
                <div className="box hidden overflow-x-auto md:block">
                  <table className="data-table min-w-[40rem]">
                    <caption className="sr-only">{dCopy.users.tableCaption}</caption>
                    <thead>
                      <tr>
                        <th scope="col">{dCopy.users.columns.email}</th>
                        <th scope="col">{dCopy.users.columns.status}</th>
                        <th scope="col">{dCopy.users.columns.access}</th>
                        <th scope="col" className="text-right">
                          <span className="sr-only">{dCopy.users.columns.actions}</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {org.users.map((u) => (
                        <tr key={u.id} className="hover:bg-surface">
                          <th scope="row" className="break-all font-mono text-xs font-semibold text-ink">
                            {u.email}
                          </th>
                          <td>
                            <Tag muted={!u.active}>{u.active ? copy.common.active : copy.common.inactive}</Tag>
                          </td>
                          <td className="text-sm text-ink">
                            {u.access.length === 0 ? (
                              <span className="text-subtle">{copy.common.none}</span>
                            ) : (
                              u.access.map(roleText).join(", ")
                            )}
                          </td>
                          <td className="text-right">{resetButton(u)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="border border-ink bg-paper md:hidden">
                  <div className="ruler-x" aria-hidden="true" />
                  <ul className="m-0 list-none divide-y divide-ink/25 p-0">
                    {org.users.map((u) => (
                      <li key={u.id} className="flex flex-col gap-3 p-4">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="break-all font-mono text-sm font-semibold text-ink">{u.email}</p>
                          <Tag muted={!u.active}>{u.active ? copy.common.active : copy.common.inactive}</Tag>
                        </div>
                        <p className="text-sm text-subtle">
                          {u.access.length === 0 ? copy.admin.users.noAccess : u.access.map(roleText).join(", ")}
                        </p>
                        {u.access.some((a) => a.role === "org_admin") && <div>{resetButton(u)}</div>}
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            )}
          </section>

          <section aria-labelledby="o-reports" className="mt-12">
            <p className="eyebrow">{dCopy.reports.eyebrow}</p>
            <h2 id="o-reports" className="heading mt-1 text-2xl lg:text-3xl">
              {dCopy.reports.heading}
            </h2>
            <p className="mb-5 mt-2 max-w-2xl text-subtle">{dCopy.reports.lead}</p>
            {org.reports.length === 0 ? (
              <LogbookEmpty
                tag={dCopy.reports.emptyTag}
                title={dCopy.reports.emptyTitle}
                artCaption={dCopy.reports.emptyArtCaption}
              />
            ) : (
              <div className="box max-h-[60vh] overflow-auto">
                <table className="data-table min-w-[44rem]">
                  <caption className="sr-only">{dCopy.reports.tableCaption}</caption>
                  <thead>
                    <tr>
                      <th scope="col">{dCopy.reports.columns.agent}</th>
                      <th scope="col">{dCopy.reports.columns.version}</th>
                      <th scope="col">{dCopy.reports.columns.semaforo}</th>
                      <th scope="col">{dCopy.reports.columns.generatedAt}</th>
                      <th scope="col">{dCopy.reports.columns.publishedAt}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {org.reports.map((r) => (
                      <tr key={r.id} className="hover:bg-surface">
                        <th scope="row" className="font-mono text-xs font-semibold text-ink">
                          {r.agent_slug}
                        </th>
                        <td className="font-mono text-sm tabular-nums text-ink">v{r.seq}</td>
                        <td>
                          <SemaforoBadge value={r.status_semaforo} />
                        </td>
                        <td className="whitespace-nowrap font-mono text-xs tabular-nums text-subtle">
                          {fmtDate(r.generated_at)}
                        </td>
                        <td className="whitespace-nowrap font-mono text-xs tabular-nums text-ink">
                          {fmtDate(r.published_at)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <Events orgId={org.id} />
        </>
      )}

      {creating && (
        <CreateAdmin
          orgId={id}
          onClose={() => setCreating(false)}
          onDone={(s) => {
            setSecret(s);
            reload();
          }}
        />
      )}
      {org && toggling && <ToggleOrg org={org} onClose={() => setToggling(false)} onDone={reload} />}
      {resetting && (
        <ConfirmModal
          title={dCopy.resetAdminModal.title(resetting.email)}
          confirmLabel={dCopy.resetAdminModal.confirm}
          onClose={() => setResetting(null)}
          onConfirm={async () => {
            const r = await opsApi.resetAdmin(id, resetting.id);
            setSecret({ title: copy.admin.users.newPasswordTitle(r.email), value: r.password });
            reload();
          }}
        >
          <p>{dCopy.resetAdminModal.body}</p>
        </ConfirmModal>
      )}
    </>
  );
}
