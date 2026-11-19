import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { copy } from "../../copy";
import { fmtDate } from "../../format";
import { opsApi } from "../../opsApi";
import { Button, ErrorBox, LogbookEmpty, LogbookLoading, PageHeader, useAsync } from "../../ui";

const PAGE = 50;

export const OPS_ACTIONS: Record<string, string> = copy.ops.activity.actions;
export const OPS_TARGETS: Record<string, string> = copy.ops.activity.targets;

export function OpsActivity() {
  const [offset, setOffset] = useState(0);
  const st = useAsync(() => opsApi.events(PAGE, offset), [offset]);
  const rows = st.data ?? [];
  const page = offset / PAGE + 1;
  const aCopy = copy.ops.activity;

  useEffect(() => {
    document.title = `${aCopy.pageTitle} · ${copy.opsBar.subtitle} · ${copy.brand.full}`;
  }, [aCopy.pageTitle]);

  return (
    <>
      <PageHeader
        crumbs={[{ label: copy.opsBar.subtitle }, { label: aCopy.crumb }]}
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
        <section aria-labelledby="ops-activity-list">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-4">
            <h2 id="ops-activity-list" className="eyebrow text-ink">
              {aCopy.listHeading}
            </h2>
            <span className="font-mono text-xs font-semibold tabular-nums text-subtle">
              {copy.common.pageLabel(page)}
            </span>
          </div>

          <div className="box max-h-[70vh] overflow-auto">
            <table className="data-table min-w-[48rem]">
              <caption className="sr-only">{aCopy.tableCaption}</caption>
              <thead>
                <tr>
                  <th scope="col">{aCopy.columns.when}</th>
                  <th scope="col">{aCopy.columns.operator}</th>
                  <th scope="col">{aCopy.columns.action}</th>
                  <th scope="col">{aCopy.columns.organization}</th>
                  <th scope="col">{aCopy.columns.target}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id} className="hover:bg-surface">
                    <td className="whitespace-nowrap font-mono text-xs tabular-nums text-ink">{fmtDate(e.at)}</td>
                    <td className="break-all font-mono text-xs text-ink">{e.operator_email}</td>
                    <td className="font-semibold text-ink">{OPS_ACTIONS[e.action] ?? e.action}</td>
                    <td>
                      {e.target_org_id !== null ? (
                        <Link
                          to={`/ops/organizations/${e.target_org_id}`}
                          className="link font-mono text-xs font-semibold"
                        >
                          {e.target_org_slug}
                        </Link>
                      ) : (
                        <span className="text-sm text-subtle">{copy.common.none}</span>
                      )}
                    </td>
                    <td className="text-sm text-ink">
                      {e.target_type ? (OPS_TARGETS[e.target_type] ?? e.target_type) : copy.common.none}
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
