import { useState } from "react";
import type { FormEvent } from "react";
import { adminApi } from "../../adminApi";
import type { AdminArea } from "../../adminApi";
import { useCatalog } from "../../auth";
import { Modal } from "../../dialogs";
import { Button, EmptyState, ErrorBox, Field, Loading, PageHeader, Select, useAsync } from "../../ui";
import { indent, orderTree, selfAndDescendants } from "./tree";

/** Create (area === null) or edit (rename and move) an area. */
function AreaForm({
  areas,
  area,
  onClose,
  onSaved,
}: {
  areas: AdminArea[];
  area: AdminArea | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(area?.name ?? "");
  const [parent, setParent] = useState(area?.parent_id == null ? "" : String(area.parent_id));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const blocked = area ? selfAndDescendants(areas, area.id) : new Set<number>();
  const options = orderTree(areas).filter((a) => !blocked.has(a.id));

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const parentId = parent === "" ? null : Number(parent);
    try {
      if (area === null) await adminApi.createArea(name.trim(), parentId);
      else {
        const body: { name?: string; parent_id?: number | null } = {};
        if (name.trim() !== area.name) body.name = name.trim();
        if (parentId !== area.parent_id) body.parent_id = parentId; // null moves it to the top level
        if (Object.keys(body).length) await adminApi.patchArea(area.id, body);
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  return (
    <Modal title={area ? "Edit area" : "Create area"} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-6">
        <Field label="Name" id="area-name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        <Select label="Parent area" id="area-parent" value={parent} onChange={(e) => setParent(e.target.value)}>
          <option value="">None (top-level area)</option>
          {options.map((a) => (
            <option key={a.id} value={a.id}>
              {indent(a.depth)}
              {a.name}
            </option>
          ))}
        </Select>
        <p className="text-sm text-subtle">
          Pick a parent to make this a sub-area. People with access to an area also see its sub-areas.
        </p>
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3">
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
            {busy ? "Saving…" : area ? "Save changes" : "Create area"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export function AdminAreas() {
  const cat = useCatalog();
  const [version, setVersion] = useState(0);
  const st = useAsync(() => adminApi.areas(), [version]);
  const [editing, setEditing] = useState<AdminArea | "new" | null>(null);
  const rows = st.data ? orderTree(st.data) : [];

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Administration" }, { label: "Areas" }]}
        title="Areas"
        lead="Areas group agents, and access is granted by area. A sub-area inherits the access of its parents. Areas cannot be deleted."
      >
        <Button variant="primary" onClick={() => setEditing("new")}>
          Create area
        </Button>
      </PageHeader>

      {st.loading && !st.data && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && rows.length === 0 && <EmptyState title="No areas yet.">Create the first area to start registering agents.</EmptyState>}
      {rows.length > 0 && (
        <div className="box overflow-x-auto">
          <table className="data-table min-w-[32rem]">
            <caption className="sr-only">Areas</caption>
            <thead>
              <tr>
                <th scope="col">Area</th>
                <th scope="col">Agents</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr key={a.id}>
                  <th scope="row">
                    <span aria-hidden="true" className="text-subtle">
                      {indent(a.depth)}
                    </span>
                    {a.name}
                    {a.depth > 0 && <span className="sr-only"> (sub-area)</span>}
                  </th>
                  <td>{a.agent_count}</td>
                  <td className="text-right">
                    <Button size="sm" onClick={() => setEditing(a)} aria-label={`Edit area ${a.name}`}>
                      Edit
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && st.data && (
        <AreaForm
          areas={st.data}
          area={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setVersion((v) => v + 1);
            cat.reload();
          }}
        />
      )}
    </>
  );
}
