import { useState } from "react";
import { Link } from "react-router-dom";
import { fmtDate } from "../../format";
import { opsApi } from "../../opsApi";
import { Button, EmptyState, ErrorBox, Loading, PageHeader, useAsync } from "../../ui";

const PAGE = 50;

export const OPS_ACTIONS: Record<string, string> = {
  "auth.login": "Signed in",
  "org.create": "Created organization",
  "org.update": "Renamed organization",
  "org.activate": "Activated organization",
  "org.deactivate": "Deactivated organization",
  "org.admin_create": "Created organization admin",
  "org.admin_password_reset": "Reset admin password",
};

export function OpsActivity() {
  const [offset, setOffset] = useState(0);
  const st = useAsync(() => opsApi.events(PAGE, offset), [offset]);
  const rows = st.data ?? [];

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Operator console" }, { label: "Activity" }]}
        title="Activity"
        lead="What operators did on the platform, newest first. Passwords are never recorded. Dates use your browser's time zone."
      />
      {st.loading && !st.data && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && rows.length === 0 && <EmptyState title={offset ? "No more events." : "No operator activity yet."} />}
      {rows.length > 0 && (
        <div className="box max-h-[70vh] overflow-auto">
          <table className="data-table min-w-[48rem]">
            <caption className="sr-only">Operator activity</caption>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Operator</th>
                <th scope="col">Action</th>
                <th scope="col">Organization</th>
                <th scope="col">Target</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id}>
                  <td className="whitespace-nowrap">{fmtDate(e.at)}</td>
                  <td className="break-all">{e.operator_email}</td>
                  <td className="font-semibold">{OPS_ACTIONS[e.action] ?? e.action}</td>
                  <td>
                    {e.target_org_id !== null ? (
                      <Link to={`/ops/organizations/${e.target_org_id}`} className="link">
                        {e.target_org_slug}
                      </Link>
                    ) : (
                      <span className="text-subtle">None</span>
                    )}
                  </td>
                  <td>
                    {e.target_type ?? ""}
                    {e.target_id !== null && <span className="text-subtle"> #{e.target_id}</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <nav aria-label="Pagination" className="mt-6 flex items-center gap-4">
        <Button size="sm" disabled={offset === 0 || st.loading} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          Newer
        </Button>
        <span className="text-sm text-subtle">Page {offset / PAGE + 1}</span>
        <Button size="sm" disabled={rows.length < PAGE || st.loading} onClick={() => setOffset(offset + PAGE)}>
          Older
        </Button>
      </nav>
    </>
  );
}
