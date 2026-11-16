import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { adminApi } from "../../adminApi";
import { useCatalog } from "../../auth";
import { Modal } from "../../dialogs";
import { fmtDate } from "../../format";
import { Button, EmptyState, ErrorBox, Field, Loading, PageHeader, Select, Tag, useAsync } from "../../ui";
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
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <Modal title="Register agent" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-6">
        <p className="text-subtle">
          The agent's area is set here. Developers only put the slug in their agent.yaml, as{" "}
          <code className="border border-ink px-1 font-mono text-sm">platform.agent_id</code>.
        </p>
        <Field label="Name" id="agent-name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        <Field
          label="Slug"
          id="agent-slug"
          required
          pattern={SLUG}
          maxLength={64}
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          hint="Lowercase letters, digits and hyphens, 1 to 64 characters. It cannot be changed later."
        />
        <Select label="Area" id="agent-area" required value={area} onChange={(e) => setArea(e.target.value)}>
          <option value="">Choose an area…</option>
          {areas.data &&
            orderTree(areas.data).map((a) => (
              <option key={a.id} value={a.id}>
                {indent(a.depth)}
                {a.name}
              </option>
            ))}
        </Select>
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3">
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !area}>
            {busy ? "Registering…" : "Register agent"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function AdminAgents() {
  const st = useAsync(() => adminApi.agents(), []);
  const [registering, setRegistering] = useState(false);

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Administration" }, { label: "Agents" }]}
        title="Agents"
        lead="Every agent that can publish reports, including inactive ones. An agent publishes with its own token."
      >
        <Button variant="primary" onClick={() => setRegistering(true)}>
          Register agent
        </Button>
      </PageHeader>

      {st.loading && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && st.data.length === 0 && (
        <EmptyState title="No agents registered yet.">Register an agent, then issue it a token so its team can publish reports.</EmptyState>
      )}
      {st.data && st.data.length > 0 && (
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
                <th scope="col">Last report</th>
              </tr>
            </thead>
            <tbody>
              {st.data.map((a) => (
                <tr key={a.id}>
                  <th scope="row">
                    <Link to={`/app/admin/agents/${a.id}`} className="link">
                      {a.name}
                    </Link>
                  </th>
                  <td className="font-mono text-sm">{a.slug}</td>
                  <td>{a.area_name}</td>
                  <td>{a.active ? <Tag>Active</Tag> : <Tag>Inactive</Tag>}</td>
                  <td>{a.tokens_active_count}</td>
                  <td className="whitespace-nowrap">{a.last_report_at ? fmtDate(a.last_report_at) : "Never"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {registering && <RegisterAgent onClose={() => setRegistering(false)} />}
    </>
  );
}
