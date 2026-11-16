import { useState } from "react";
import { adminApi } from "../../adminApi";
import { fmtDate } from "../../format";
import { Button, EmptyState, ErrorBox, Loading, PageHeader, useAsync } from "../../ui";

const PAGE = 50;

const ACTIONS: Record<string, string> = {
  "area.create": "Created area",
  "area.update": "Edited area",
  "agent.create": "Registered agent",
  "agent.update": "Edited agent",
  "agent.activate": "Activated agent",
  "agent.deactivate": "Deactivated agent",
  "token.issue": "Issued agent token",
  "token.revoke": "Revoked agent token",
  "user.create": "Created user",
  "user.update": "Edited user",
  "user.activate": "Activated user",
  "user.deactivate": "Deactivated user",
  "user.password_change": "Changed user password",
  "membership.create": "Granted access",
  "membership.delete": "Revoked access",
};
const TARGETS: Record<string, string> = {
  area: "Area",
  agent: "Agent",
  agent_token: "Token",
  user: "User",
  membership: "Access grant",
};

export function AdminActivity() {
  const [offset, setOffset] = useState(0);
  const st = useAsync(() => adminApi.events(PAGE, offset), [offset]);
  const rows = st.data ?? [];
  const page = offset / PAGE + 1;

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Administration" }, { label: "Activity" }]}
        title="Activity"
        lead="Who changed what in the administration, newest first. Passwords and tokens are never recorded. Dates use your browser's time zone."
      />

      {st.loading && !st.data && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && rows.length === 0 && <EmptyState title={offset ? "No more events." : "No administrative activity yet."} />}
      {rows.length > 0 && (
        <div className="box max-h-[70vh] overflow-auto">
          <table className="data-table min-w-[44rem]">
            <caption className="sr-only">Administrative activity</caption>
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
                  <td className="break-all">{e.actor_email ?? (e.actor_user_id === null ? "Bootstrap key" : `User #${e.actor_user_id}`)}</td>
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
      <nav aria-label="Pagination" className="mt-6 flex items-center gap-4">
        <Button size="sm" disabled={offset === 0 || st.loading} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          Newer
        </Button>
        <span className="text-sm text-subtle">Page {page}</span>
        <Button size="sm" disabled={rows.length < PAGE || st.loading} onClick={() => setOffset(offset + PAGE)}>
          Older
        </Button>
      </nav>
    </>
  );
}
