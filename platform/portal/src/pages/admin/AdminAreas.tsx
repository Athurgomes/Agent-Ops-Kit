import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { adminApi } from "../../adminApi";
import type { AdminArea } from "../../adminApi";
import { useCatalog } from "../../auth";
import { copy } from "../../copy";
import { Modal } from "../../dialogs";
import { fmtApiError } from "../../format";
import {
  Button,
  ErrorBox,
  Field,
  LogbookEmpty,
  LogbookLoading,
  PageHeader,
  Select,
  useAsync,
} from "../../ui";
import { indent, orderTree, selfAndDescendants } from "./tree";

const fmtIdx = (i: number) => String(i + 1).padStart(2, "0");

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
      setError(fmtApiError(err));
      setBusy(false);
    }
  }

  return (
    <Modal
      title={area ? copy.admin.areas.form.editTitle : copy.admin.areas.form.createTitle}
      onClose={onClose}
    >
      <form onSubmit={submit} className="flex flex-col gap-6">
        <Field
          label={copy.admin.areas.form.nameLabel}
          id="area-name"
          required
          maxLength={200}
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <Select
          label={copy.admin.areas.form.parentLabel}
          id="area-parent"
          value={parent}
          onChange={(e) => setParent(e.target.value)}
        >
          <option value="">{copy.admin.areas.form.parentNone}</option>
          {options.map((a) => (
            <option key={a.id} value={a.id}>
              {indent(a.depth)}
              {a.name}
            </option>
          ))}
        </Select>
        <p className="text-sm text-subtle">{copy.admin.areas.form.parentHint}</p>
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3 border-t border-line pt-4">
          <Button onClick={onClose} disabled={busy}>
            {copy.common.cancel}
          </Button>
          <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
            {busy ? copy.common.saving : area ? copy.common.saveChanges : copy.admin.areas.form.createSubmit}
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

  useEffect(() => {
    document.title = `${copy.admin.areas.pageTitle} · ${copy.brand.full}`;
  }, []);

  return (
    <>
      <PageHeader
        crumbs={[{ label: copy.admin.crumbRoot }, { label: copy.admin.areas.crumb }]}
        title={copy.admin.areas.title}
        lead={copy.admin.areas.lead}
        stamp={copy.admin.areas.stamp}
      >
        <Button variant="primary" onClick={() => setEditing("new")}>
          {copy.admin.areas.createAction}
        </Button>
      </PageHeader>

      {st.loading && !st.data && (
        <LogbookLoading label={copy.admin.areas.loadingLabel} caption={copy.admin.areas.loadingCaption} />
      )}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && rows.length === 0 && (
        <LogbookEmpty
          tag={copy.admin.areas.emptyTag}
          title={copy.admin.areas.emptyTitle}
          artCaption={copy.admin.areas.emptyArtCaption}
        >
          {copy.admin.areas.emptyBody}
        </LogbookEmpty>
      )}
      {rows.length > 0 && (
        <section aria-labelledby="admin-areas-list">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-4">
            <h2 id="admin-areas-list" className="eyebrow text-ink">
              {copy.admin.areas.listHeading}
            </h2>
            <span className="font-mono text-xs font-semibold tabular-nums text-subtle">
              {copy.admin.areas.countLabel(rows.length)}
            </span>
          </div>

          <div className="box overflow-x-auto">
            <table className="data-table min-w-[32rem]">
              <caption className="sr-only">{copy.admin.areas.tableCaption}</caption>
              <thead>
                <tr>
                  <th scope="col" className="w-20">
                    {copy.admin.areas.columns.index}
                  </th>
                  <th scope="col">{copy.admin.areas.columns.area}</th>
                  <th scope="col" className="w-28">
                    {copy.admin.areas.columns.agents}
                  </th>
                  <th scope="col" className="w-28 text-right">
                    <span className="sr-only">{copy.admin.areas.columns.actions}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((a, idx) => (
                  <tr key={a.id} className="hover:bg-surface">
                    <td className="font-mono text-xs font-semibold tabular-nums text-subtle">{fmtIdx(idx)}</td>
                    <th scope="row">
                      {a.depth > 0 && (
                        <span aria-hidden="true" className="mr-1 font-mono text-xs font-normal text-subtle">
                          {indent(a.depth)}
                        </span>
                      )}
                      <span className={a.depth === 0 ? "font-display text-lg font-extrabold text-ink" : "font-semibold text-ink"}>
                        {a.name}
                      </span>
                      {a.depth > 0 && <span className="sr-only">{copy.admin.areas.subareaSr}</span>}
                    </th>
                    <td className="font-mono text-sm tabular-nums text-ink">
                      {String(a.agent_count).padStart(2, "0")}
                    </td>
                    <td className="text-right">
                      <Button size="sm" onClick={() => setEditing(a)} aria-label={copy.admin.areas.editAria(a.name)}>
                        {copy.common.edit}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
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
