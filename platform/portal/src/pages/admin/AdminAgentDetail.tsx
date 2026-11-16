import { useState } from "react";
import type { FormEvent } from "react";
import { useParams } from "react-router-dom";
import { adminApi } from "../../adminApi";
import type { AdminAgent, IssuedToken, TokenMeta } from "../../adminApi";
import { useCatalog } from "../../auth";
import { ConfirmModal, Modal, OneTimeSecret } from "../../dialogs";
import { fmtDate } from "../../format";
import { Button, EmptyState, ErrorBox, Field, Loading, PageHeader, Select, Tag, useAsync } from "../../ui";
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
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <Modal title="Edit agent" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-6">
        <Field label="Name" id="edit-agent-name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        <Select label="Area" id="edit-agent-area" value={area} onChange={(e) => setArea(e.target.value)}>
          {areas.data &&
            orderTree(areas.data).map((a) => (
              <option key={a.id} value={a.id}>
                {indent(a.depth)}
                {a.name}
              </option>
            ))}
        </Select>
        <p className="text-sm text-subtle">The slug cannot be changed: it identifies the agent in published reports.</p>
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3">
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
            {busy ? "Saving…" : "Save changes"}
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
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setIssuing(false);
    }
  }

  return (
    <section aria-labelledby="tokens" className="mt-12">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 id="tokens" className="heading text-2xl">
            Tokens
          </h2>
          <p className="mt-1 max-w-2xl text-subtle">
            A token lets this agent's team publish reports for this agent only. It cannot read anything, and you can
            revoke it at any time.
          </p>
        </div>
        <Button variant="primary" onClick={issue} disabled={issuing || !agent.active}>
          {issuing ? "Issuing…" : "Issue token"}
        </Button>
      </div>
      {!agent.active && <p className="mb-4 text-sm text-subtle">An inactive agent cannot publish. Activate it to issue tokens.</p>}
      {error && <ErrorBox>{error}</ErrorBox>}

      {issued && (
        <div className="mb-6">
          <OneTimeSecret
            title="New token"
            announcement="Token issued. Shown once; store it now."
            secret={issued.token}
            onDismiss={() => setIssued(null)}
            extra={
              <div className="mt-6 border-t border-ink pt-4 text-sm">
                <p className="mb-2 font-bold">Use it where the agent is tested:</p>
                <pre className="m-0 overflow-x-auto border border-ink bg-white p-3 font-mono text-sm">{`export AOK_PLATFORM_TOKEN="${issued.token}"
aok check --config agent.yaml --publish https://<your-platform> --agent-id ${agent.slug}`}</pre>
              </div>
            }
          />
        </div>
      )}

      {st.loading && !st.data && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && st.data.length === 0 && <EmptyState title="No tokens yet.">Issue one so the team can publish.</EmptyState>}
      {st.data && st.data.length > 0 && (
        <div className="box hidden overflow-x-auto md:block">
          <table className="data-table min-w-[32rem]">
            <caption className="sr-only">Tokens of {agent.name}</caption>
            <thead>
              <tr>
                <th scope="col">Token</th>
                <th scope="col">Created</th>
                <th scope="col">Last used</th>
                <th scope="col">Status</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {st.data.map((t) => (
                <tr key={t.token_id}>
                  <th scope="row">#{t.token_id}</th>
                  <td className="whitespace-nowrap">{fmtDate(t.created_at)}</td>
                  <td className="whitespace-nowrap">{t.last_used_at ? fmtDate(t.last_used_at) : "Never"}</td>
                  <td>{t.revoked_at ? <Tag>Revoked {fmtDate(t.revoked_at)}</Tag> : <Tag>Active</Tag>}</td>
                  <td className="text-right">
                    {!t.revoked_at && (
                      <Button size="sm" onClick={() => setRevoking(t)} aria-label={`Revoke token ${t.token_id}`}>
                        Revoke
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
        <ul className="m-0 list-none p-0 md:hidden">
          {st.data.map((t) => (
            <li key={t.token_id} className="rule-t flex flex-col gap-2 py-4 last:border-b last:border-ink">
              <p className="flex flex-wrap items-center gap-3">
                <span className="font-bold">Token #{t.token_id}</span>
                {t.revoked_at ? <Tag>Revoked {fmtDate(t.revoked_at)}</Tag> : <Tag>Active</Tag>}
              </p>
              <p className="text-sm text-subtle">
                Created {fmtDate(t.created_at)} · Last used {t.last_used_at ? fmtDate(t.last_used_at) : "never"}
              </p>
              {!t.revoked_at && (
                <div>
                  <Button size="sm" onClick={() => setRevoking(t)} aria-label={`Revoke token ${t.token_id}`}>
                    Revoke
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      {revoking && (
        <ConfirmModal
          title={`Revoke token #${revoking.token_id}?`}
          confirmLabel="Revoke token"
          onClose={() => setRevoking(null)}
          onConfirm={async () => {
            await adminApi.revokeToken(agent.id, revoking.token_id);
            setVersion((v) => v + 1);
            onChanged();
          }}
        >
          <p>Publishing with this token will fail right away. This cannot be undone; issue a new token if needed.</p>
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

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Administration" }, { label: "Agents", to: "/app/admin/agents" }, { label: agent?.name ?? "Agent" }]}
        title={agent?.name ?? "Agent"}
      >
        {agent && (
          <div className="flex flex-wrap gap-3">
            <Button onClick={() => setEditing(true)}>Edit</Button>
            <Button onClick={() => setToggling(true)}>{agent.active ? "Deactivate" : "Activate"}</Button>
          </div>
        )}
      </PageHeader>

      {st.loading && !st.data && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && !agent && <EmptyState title="Agent not found." />}
      {agent && (
        <>
          <dl className="box m-0 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
            {[
              ["Slug", <span key="s" className="font-mono text-sm">{agent.slug}</span>],
              ["Area", agent.area_name],
              ["Status", agent.active ? "Active" : "Inactive"],
              ["Last report", agent.last_report_at ? fmtDate(agent.last_report_at) : "Never"],
            ].map(([k, v], i) => (
              <div key={i} className="p-4 sm:border-r sm:border-ink sm:last:border-r-0">
                <dt className="text-sm text-subtle">{k}</dt>
                <dd className="m-0 font-bold">{v}</dd>
              </div>
            ))}
          </dl>
          <TokenPanel agent={agent} onChanged={() => setVersion((v) => v + 1)} />
        </>
      )}

      {agent && editing && <EditAgent agent={agent} onClose={() => setEditing(false)} onSaved={reload} />}
      {agent && toggling && (
        <ConfirmModal
          title={agent.active ? `Deactivate ${agent.name}?` : `Activate ${agent.name}?`}
          confirmLabel={agent.active ? "Deactivate" : "Activate"}
          onClose={() => setToggling(false)}
          onConfirm={async () => {
            await adminApi.patchAgent(agent.id, { active: !agent.active });
            reload();
          }}
        >
          <p>
            {agent.active
              ? "An inactive agent cannot publish new reports. Existing reports stay visible. You can activate it again."
              : "The agent will be able to publish reports again with its active tokens."}
          </p>
        </ConfirmModal>
      )}
    </>
  );
}
