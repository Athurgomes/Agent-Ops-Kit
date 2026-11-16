import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ConfirmModal, Modal } from "../../dialogs";
import { fmtDate } from "../../format";
import { opsApi } from "../../opsApi";
import type { OpsOrg } from "../../opsApi";
import { Button, EmptyState, ErrorBox, Field, Loading, PageHeader, Tag, useAsync } from "../../ui";

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
  return (
    <ConfirmModal
      title={org.active ? `Deactivate ${org.name}?` : `Activate ${org.name}?`}
      confirmLabel={org.active ? "Deactivate" : "Activate"}
      onClose={onClose}
      onConfirm={async () => {
        await opsApi.patchOrg(org.id, { active: !org.active });
        onDone();
      }}
    >
      <p>
        {org.active
          ? "Users of this organization will not be able to sign in and agent tokens stop working; nothing is deleted. You can activate it again."
          : "Users of this organization will be able to sign in again and agent tokens work again."}
      </p>
    </ConfirmModal>
  );
}

function CreateOrg({ onClose }: { onClose: () => void }) {
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const o = await opsApi.createOrg(slug, name.trim());
      onClose();
      nav(`/ops/organizations/${o.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <Modal title="Create organization" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-6">
        <Field label="Name" id="org-name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        <Field
          label="Slug"
          id="org-slug"
          required
          pattern={SLUG}
          maxLength={64}
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          hint="Lowercase letters, digits and hyphens, 1 to 64 characters. It is unique and identifies the organization."
        />
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3">
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
            {busy ? "Creating…" : "Create organization"}
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

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Operator console" }, { label: "Organizations" }]}
        title="Organizations"
        lead="Every organization on the platform. You see counts and metadata only; report contents are not available here."
      >
        <Button variant="primary" onClick={() => setCreating(true)}>
          Create organization
        </Button>
      </PageHeader>

      {st.loading && !st.data && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && st.data.length === 0 && <EmptyState title="No organizations yet." />}
      {st.data && st.data.length > 0 && (
        <div className="box overflow-x-auto">
          <table className="data-table min-w-[64rem]">
            <caption className="sr-only">Organizations</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Slug</th>
                <th scope="col">Status</th>
                <th scope="col">Areas</th>
                <th scope="col">Agents</th>
                <th scope="col">Users</th>
                <th scope="col">Active tokens</th>
                <th scope="col">Reports</th>
                <th scope="col">Last report</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {st.data.map((o) => (
                <tr key={o.id}>
                  <th scope="row">
                    <Link to={`/ops/organizations/${o.id}`} className="link">
                      {o.name}
                    </Link>
                  </th>
                  <td className="font-mono text-sm">{o.slug}</td>
                  <td>{o.active ? <Tag>Active</Tag> : <Tag>Inactive</Tag>}</td>
                  <td>{o.areas_count}</td>
                  <td>{o.agents_count}</td>
                  <td>{o.users_count}</td>
                  <td>{o.tokens_active_count}</td>
                  <td>{o.reports_count}</td>
                  <td className="whitespace-nowrap">{o.last_report_at ? fmtDate(o.last_report_at) : "Never"}</td>
                  <td className="text-right">
                    <Button size="sm" onClick={() => setToggling(o)} aria-label={`${o.active ? "Deactivate" : "Activate"} ${o.name}`}>
                      {o.active ? "Deactivate" : "Activate"}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creating && <CreateOrg onClose={() => setCreating(false)} />}
      {toggling && <ToggleOrg org={toggling} onClose={() => setToggling(null)} onDone={() => setVersion((v) => v + 1)} />}
    </>
  );
}
