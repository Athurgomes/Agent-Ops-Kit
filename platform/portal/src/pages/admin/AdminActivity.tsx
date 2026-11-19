import { useEffect, useState } from "react";
import { adminApi } from "../../adminApi";
import { copy } from "../../copy";
import { fmtDate } from "../../format";
import { Button, ErrorBox, LogbookEmpty, LogbookLoading, PageHeader, useAsync } from "../../ui";

const PAGE = 50;

export const ACTIONS: Record<string, string> = copy.admin.activity.actions;
export const TARGETS: Record<string, string> = copy.admin.activity.targets;

export function AdminActivity() {
  const [offset, setOffset] = useState(0);
  const st = useAsync(() => adminApi.events(PAGE, offset), [offset]);
  const rows = st.data ?? [];
  const page = offset / PAGE + 1;
  const aCopy = copy.admin.activity;

  useEffect(() => {
    document.title = `${aCopy.pageTitle} · ${copy.brand.full}`;
  }, [aCopy.pageTitle]);

  return (
    <>
      <PageHeader
        crumbs={[{ label: copy.admin.crumbRoot }, { label: aCopy.crumb }]}
        title={aCopy.title}
        lead={aCopy.lead}
        stamp={aCopy.stamp}
      />

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
        <section aria-labelledby="admin-activity-list">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-4">
            <h2 id="admin-activity-list" className="eyebrow text-ink">
              {aCopy.listHeading}
            </h2>
            <span className="font-mono text-xs font-semibold tabular-nums text-subtle">
              {copy.common.pageLabel(page)}
            </span>
          </div>

          <div className="box max-h-[70vh] overflow-auto">
            <table className="data-table min-w-[44rem]">
              <caption className="sr-only">{aCopy.tableCaption}</caption>
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
                      {e.actor_email ??
                        (e.actor_user_id === null ? aCopy.bootstrapKey : aCopy.userRef(e.actor_user_id))}
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
        </section>
      )}
      <nav
        aria-label={copy.common.paginationAria}
        className="mt-6 flex flex-wrap items-center gap-4 border-t border-line pt-5"
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
    </>
  );
}
