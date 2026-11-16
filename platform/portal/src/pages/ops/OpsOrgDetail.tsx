import { useState } from "react";
import type { FormEvent } from "react";
import { useParams } from "react-router-dom";
import { ConfirmModal, Modal, OneTimeSecret } from "../../dialogs";
import { fmtDate } from "../../format";
import { opsApi } from "../../opsApi";
import type { OpsAreaNode, OpsDetail, OpsUser } from "../../opsApi";
import { Button, EmptyState, ErrorBox, Field, Loading, PageHeader, SemaforoBadge, Tag, useAsync } from "../../ui";
import { ACTIONS, TARGETS } from "../admin/AdminActivity";
import { ToggleOrg } from "./OpsOrganizations";

type Secret = { title: string; value: string };

const SECURE_CHANNEL = "Send it to the admin through a secure channel outside Farol. There is no email, and it will not be shown again.";

function CreateAdmin({ orgId, onClose, onDone }: { orgId: number; onClose: () => void; onDone: (s: Secret) => void }) {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await opsApi.createAdmin(orgId, email.trim());
      onDone({ title: `Initial password for ${r.email}`, value: r.password });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <Modal title="Create admin" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-6">
        <p className="text-subtle">
          Creates an organization admin. The server generates a random password and shows it once, right after.
        </p>
        <Field label="Email" id="admin-email" type="email" required maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3">
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !email.trim()}>
            {busy ? "Creating…" : "Create admin"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function Tree({ nodes }: { nodes: OpsAreaNode[] }) {
  return (
    <ul className="m-0 list-none p-0">
      {nodes.map((n) => (
        <li key={n.id} className="py-1">
          <span className="font-semibold">{n.name}</span>
          {n.children.length > 0 && (
            <div className="ml-3 mt-1 border-l border-ink pl-4">
              <Tree nodes={n.children} />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

const roleText = (a: { role: string; area_name: string | null }) =>
  a.role === "org_admin" ? "Organization admin" : `${a.area_name ?? "Area"} (viewer)`;

function Events({ orgId }: { orgId: number }) {
  const PAGE = 20;
  const [offset, setOffset] = useState(0);
  const st = useAsync(() => opsApi.orgEvents(orgId, PAGE, offset), [orgId, offset]);
  const rows = st.data ?? [];
  return (
    <section aria-labelledby="org-events" className="mt-12">
      <h2 id="org-events" className="heading mb-2 text-2xl">
        Organization activity
      </h2>
      <p className="mb-4 max-w-2xl text-subtle">Administrative changes made inside this organization, newest first. Read only.</p>
      {st.loading && !st.data && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && rows.length === 0 && <EmptyState title={offset ? "No more events." : "No administrative activity yet."} />}
      {rows.length > 0 && (
        <div className="box overflow-x-auto">
          <table className="data-table min-w-[36rem]">
            <caption className="sr-only">Organization activity</caption>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Who</th>
                <th scope="col">Action</th>
                <th scope="col">Target</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id}>
                  <td className="whitespace-nowrap">{fmtDate(e.at)}</td>
                  <td className="break-all">{e.actor_email ?? "Bootstrap key"}</td>
                  <td className="font-semibold">{ACTIONS[e.action] ?? e.action}</td>
                  <td>
                    {TARGETS[e.target_type] ?? e.target_type}
                    {e.target_id !== null && <span className="text-subtle"> #{e.target_id}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <nav aria-label="Organization activity pagination" className="mt-4 flex items-center gap-4">
        <Button size="sm" disabled={offset === 0 || st.loading} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          Newer
        </Button>
        <span className="text-sm text-subtle">Page {offset / PAGE + 1}</span>
        <Button size="sm" disabled={rows.length < PAGE || st.loading} onClick={() => setOffset(offset + PAGE)}>
          Older
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

  const resetButton = (u: OpsUser) =>
    u.access.some((a) => a.role === "org_admin") && (
      <Button size="sm" onClick={() => setResetting(u)} aria-label={`Reset password for ${u.email}`}>
        Reset password
      </Button>
    );

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Operator console" }, { label: "Organizations", to: "/ops/organizations" }, { label: org?.name ?? "Organization" }]}
        title={org?.name ?? "Organization"}
        lead={org ? <span className="font-mono text-sm">{org.slug}</span> : undefined}
      >
        {org && (
          <div className="flex flex-wrap gap-3">
            <Button variant="primary" onClick={() => setCreating(true)}>
              Create admin
            </Button>
            <Button onClick={() => setToggling(true)}>{org.active ? "Deactivate" : "Activate"}</Button>
          </div>
        )}
      </PageHeader>

      <p className="box mb-12 border-l-4 border-l-accent p-4 font-semibold">
        The operator view shows metadata only. Report contents are not available here.
      </p>

      {secret && (
        <div className="mb-12">
          <OneTimeSecret
            title={secret.title}
            announcement="Password generated. Shown once; store it now."
            secret={secret.value}
            onDismiss={() => setSecret(null)}
            extra={<p className="mt-4 text-sm">{SECURE_CHANNEL}</p>}
          />
        </div>
      )}

      {st.loading && !org && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {org && (
        <>
          <p className="mb-8">
            Status: {org.active ? <Tag>Active</Tag> : <Tag>Inactive</Tag>}{" "}
            <span className="text-subtle">Created {fmtDate(org.created_at)}</span>
          </p>

          <section aria-labelledby="o-areas">
            <h2 id="o-areas" className="heading mb-4 text-2xl">
              Areas
            </h2>
            {org.areas.length === 0 ? <EmptyState title="No areas yet." /> : <div className="box p-4"><Tree nodes={org.areas} /></div>}
          </section>

          <section aria-labelledby="o-agents" className="mt-12">
            <h2 id="o-agents" className="heading mb-4 text-2xl">
              Agents
            </h2>
            {org.agents.length === 0 ? (
              <EmptyState title="No agents yet." />
            ) : (
              <div className="box overflow-x-auto">
                <table className="data-table min-w-[48rem]">
                  <caption className="sr-only">Agents</caption>
                  <thead>
                    <tr>
                      <th scope="col">Name</th>
                      <th scope="col">Slug</th>
                      <th scope="col">Area</th>
                      <th scope="col">Status</th>
                      <th scope="col">Active tokens</th>
                      <th scope="col">Latest traffic light</th>
                      <th scope="col">Last report</th>
                    </tr>
                  </thead>
                  <tbody>
                    {org.agents.map((a) => (
                      <tr key={a.id}>
                        <th scope="row">{a.name}</th>
                        <td className="font-mono text-sm">{a.slug}</td>
                        <td>{a.area_name}</td>
                        <td>{a.active ? <Tag>Active</Tag> : <Tag>Inactive</Tag>}</td>
                        <td>{a.tokens_active_count}</td>
                        <td>{a.latest_semaforo ? <SemaforoBadge value={a.latest_semaforo} /> : <span className="text-subtle">No report</span>}</td>
                        <td className="whitespace-nowrap">{a.last_report_at ? fmtDate(a.last_report_at) : "Never"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section aria-labelledby="o-users" className="mt-12">
            <h2 id="o-users" className="heading mb-4 text-2xl">
              Users
            </h2>
            {org.users.length === 0 ? (
              <EmptyState title="No users yet.">Create an admin so the organization can sign in.</EmptyState>
            ) : (
              <>
                <div className="box hidden overflow-x-auto md:block">
                  <table className="data-table min-w-[40rem]">
                    <caption className="sr-only">Users</caption>
                    <thead>
                      <tr>
                        <th scope="col">Email</th>
                        <th scope="col">Status</th>
                        <th scope="col">Access</th>
                        <th scope="col">
                          <span className="sr-only">Actions</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {org.users.map((u) => (
                        <tr key={u.id}>
                          <th scope="row" className="break-all">
                            {u.email}
                          </th>
                          <td>{u.active ? <Tag>Active</Tag> : <Tag>Inactive</Tag>}</td>
                          <td>{u.access.length === 0 ? <span className="text-subtle">None</span> : u.access.map(roleText).join(", ")}</td>
                          <td className="text-right">{resetButton(u)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <ul className="m-0 list-none p-0 md:hidden">
                  {org.users.map((u) => (
                    <li key={u.id} className="rule-t flex flex-col gap-3 py-5 last:border-b last:border-ink">
                      <p className="break-all font-bold">{u.email}</p>
                      <p className="flex flex-wrap items-center gap-3 text-sm">
                        {u.active ? <Tag>Active</Tag> : <Tag>Inactive</Tag>}
                        <span className="text-subtle">{u.access.length === 0 ? "No access" : u.access.map(roleText).join(", ")}</span>
                      </p>
                      <div>{resetButton(u)}</div>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>

          <section aria-labelledby="o-reports" className="mt-12">
            <h2 id="o-reports" className="heading mb-2 text-2xl">
              Report versions
            </h2>
            <p className="mb-4 max-w-2xl text-subtle">Only who published what, when, and the traffic light. The reports themselves are not shown.</p>
            {org.reports.length === 0 ? (
              <EmptyState title="No reports published yet." />
            ) : (
              <div className="box max-h-[60vh] overflow-auto">
                <table className="data-table min-w-[44rem]">
                  <caption className="sr-only">Report versions</caption>
                  <thead>
                    <tr>
                      <th scope="col">Agent</th>
                      <th scope="col">Version</th>
                      <th scope="col">Traffic light</th>
                      <th scope="col">Generated</th>
                      <th scope="col">Published</th>
                    </tr>
                  </thead>
                  <tbody>
                    {org.reports.map((r) => (
                      <tr key={r.id}>
                        <th scope="row" className="font-mono text-sm">
                          {r.agent_slug}
                        </th>
                        <td>{r.seq}</td>
                        <td>
                          <SemaforoBadge value={r.status_semaforo} />
                        </td>
                        <td className="whitespace-nowrap">{fmtDate(r.generated_at)}</td>
                        <td className="whitespace-nowrap">{fmtDate(r.published_at)}</td>
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

      {creating && <CreateAdmin orgId={id} onClose={() => setCreating(false)} onDone={(s) => { setSecret(s); reload(); }} />}
      {org && toggling && <ToggleOrg org={org} onClose={() => setToggling(false)} onDone={reload} />}
      {resetting && (
        <ConfirmModal
          title={`Reset password for ${resetting.email}?`}
          confirmLabel="Reset password"
          onClose={() => setResetting(null)}
          onConfirm={async () => {
            const r = await opsApi.resetAdmin(id, resetting.id);
            setSecret({ title: `New password for ${r.email}`, value: r.password });
            reload();
          }}
        >
          <p>A new random password will be generated and shown once. This ends all of the admin's sessions, and the old password stops working.</p>
        </ConfirmModal>
      )}
    </>
  );
}
