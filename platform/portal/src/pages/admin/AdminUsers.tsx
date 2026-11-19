import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { adminApi } from "../../adminApi";
import type { AdminUser, Role } from "../../adminApi";
import { useAuth } from "../../auth";
import { copy } from "../../copy";
import { ConfirmModal, Modal, OneTimeSecret } from "../../dialogs";
import { fmtApiError } from "../../format";
import { generatePassword } from "../../password";
import {
  Button,
  cx,
  ErrorBox,
  Field,
  LogbookEmpty,
  LogbookLoading,
  PageHeader,
  Select,
  Tag,
  useAsync,
} from "../../ui";
import { indent, orderTree } from "./tree";

type Secret = { title: string; value: string };

const fmtIdx = (i: number) => String(i + 1).padStart(2, "0");

const roleLabel = (r: string) =>
  r === "org_admin" ? copy.admin.roles.orgAdmin : copy.admin.roles.areaViewer;

function AreaOptions() {
  const areas = useAsync(() => adminApi.areas(), []);
  return (
    <>
      {areas.data &&
        orderTree(areas.data).map((a) => (
          <option key={a.id} value={a.id}>
            {indent(a.depth)}
            {a.name}
          </option>
        ))}
    </>
  );
}

function CreateUser({ onClose, onDone }: { onClose: () => void; onDone: (secret: Secret | null) => void }) {
  const areas = useAsync(() => adminApi.areas(), []);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [generated, setGenerated] = useState(false);
  const [access, setAccess] = useState("none");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [createdId, setCreatedId] = useState<number | null>(null); // set once the account exists

  const fCopy = copy.admin.users.createForm;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (createdId !== null) return; // never create twice
    setBusy(true);
    setError(null);
    let userId: number | null = null;
    try {
      userId = (await adminApi.createUser(email.trim(), password)).id;
      setCreatedId(userId);
      if (access === "admin") await adminApi.grant(userId, "org_admin", null);
      else if (access.startsWith("area:")) await adminApi.grant(userId, "area_viewer", Number(access.slice(5)));
      onDone(generated ? { title: copy.admin.users.initialPasswordTitle(email.trim()), value: password } : null);
      onClose();
    } catch (err) {
      const msg = fmtApiError(err);
      if (userId !== null) {
        // the user exists but the access step failed: say so, and do not offer to create it again
        onDone(generated ? { title: copy.admin.users.initialPasswordTitle(email.trim()), value: password } : null);
        setError(fCopy.partialGrantError(msg));
        setBusy(false);
        return;
      }
      setError(msg);
      setBusy(false);
    }
  }

  return (
    <Modal title={fCopy.title} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-6">
        <Field
          label={fCopy.emailLabel}
          id="user-email"
          type="email"
          required
          maxLength={254}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoFocus
        />
        <div className="flex flex-col gap-2">
          <Field
            label={fCopy.passwordLabel}
            id="user-password"
            type={generated ? "text" : "password"}
            autoComplete="new-password"
            required
            minLength={12}
            maxLength={256}
            value={password}
            onChange={(e) => {
              setPassword(e.target.value);
              setGenerated(false);
            }}
            hint={fCopy.passwordHint}
          />
          <div>
            <Button
              size="sm"
              onClick={() => {
                setPassword(generatePassword());
                setGenerated(true);
              }}
            >
              {fCopy.generateAction}
            </Button>
          </div>
        </div>
        <Select label={fCopy.accessLabel} id="user-access" value={access} onChange={(e) => setAccess(e.target.value)}>
          <option value="none">{fCopy.accessNone}</option>
          <option value="admin">{fCopy.accessAdmin}</option>
          {areas.data &&
            orderTree(areas.data).map((a) => (
              <option key={a.id} value={`area:${a.id}`}>
                {fCopy.accessViewerPrefix}
                {indent(a.depth)}
                {a.name}
              </option>
            ))}
        </Select>
        <p className="text-sm text-subtle">{fCopy.accessHint}</p>
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3 border-t border-line pt-4">
          <Button onClick={onClose} disabled={busy}>
            {createdId !== null ? copy.common.close : copy.common.cancel}
          </Button>
          {createdId === null && (
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? fCopy.submitting : fCopy.submit}
            </Button>
          )}
        </div>
      </form>
    </Modal>
  );
}

function ResetPassword({ user, onClose, onDone }: { user: AdminUser; onClose: () => void; onDone: (s: Secret) => void }) {
  const [password] = useState(() => generatePassword());
  return (
    <ConfirmModal
      title={copy.admin.users.resetModal.title(user.email)}
      confirmLabel={copy.admin.users.resetModal.confirm}
      onClose={onClose}
      onConfirm={async () => {
        await adminApi.patchUser(user.id, { password });
        onDone({ title: copy.admin.users.newPasswordTitle(user.email), value: password });
      }}
    >
      <p>{copy.admin.users.resetModal.body}</p>
    </ConfirmModal>
  );
}

function ManageAccess({
  userId,
  users,
  onClose,
  onChanged,
}: {
  userId: number;
  users: AdminUser[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const { me } = useAuth();
  const user = users.find((u) => u.id === userId);
  const [role, setRole] = useState<Role>("area_viewer");
  const [area, setArea] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<number | null>(null);
  if (!user) return null;

  const mCopy = copy.admin.users.manageAccess;

  async function grant(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await adminApi.grant(userId, role, role === "org_admin" ? null : Number(area));
      onChanged();
      setArea("");
    } catch (err) {
      setError(fmtApiError(err));
    } finally {
      setBusy(false);
    }
  }
  async function revoke(id: number) {
    setBusy(true);
    setError(null);
    try {
      await adminApi.revokeAccess(id);
      setConfirming(null);
      onChanged();
    } catch (err) {
      setError(fmtApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={mCopy.title(user.email)} onClose={onClose} wide>
      <div className="flex flex-col gap-6">
        <p className="text-subtle">{mCopy.lead}</p>
        {user.memberships.length === 0 ? (
          <p className="border border-line bg-surface px-4 py-3 text-sm font-semibold text-ink">{mCopy.empty}</p>
        ) : (
          <ul className="m-0 list-none border border-ink p-0">
            {user.memberships.map((m) => {
              const own = me?.id === user.id && m.role === "org_admin";
              const targetLabel =
                m.role === "org_admin" ? copy.admin.roles.orgAdmin : (m.area_name ?? copy.admin.roles.areaFallback);
              return (
                <li
                  key={m.id}
                  className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 last:border-b-0"
                >
                  <span>
                    <span className="font-semibold text-ink">{targetLabel}</span>
                    {m.role !== "org_admin" && <span className="text-subtle"> · {roleLabel(m.role)}</span>}
                  </span>
                  {confirming === m.id ? (
                    <span className="flex flex-wrap items-center gap-2">
                      <Button size="sm" variant="dark" disabled={busy} onClick={() => revoke(m.id)}>
                        {mCopy.confirmRevoke}
                      </Button>
                      <Button size="sm" disabled={busy} onClick={() => setConfirming(null)}>
                        {copy.common.cancel}
                      </Button>
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      disabled={busy || own}
                      aria-describedby={own ? `own-admin-note-${m.id}` : undefined}
                      onClick={() => setConfirming(m.id)}
                      aria-label={mCopy.revokeAria(targetLabel)}
                    >
                      {mCopy.revoke}
                    </Button>
                  )}
                  {own && (
                    <p id={`own-admin-note-${m.id}`} className="w-full text-sm text-subtle">
                      {mCopy.ownAdminNote}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        <form onSubmit={grant} className="border border-ink bg-surface p-5">
          <p className="eyebrow mb-4 text-ink">{mCopy.grantHeading}</p>
          <div className="flex flex-col gap-4">
            <Select label={mCopy.roleLabel} id="grant-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              <option value="area_viewer">{copy.admin.roles.areaViewer}</option>
              <option value="org_admin">{copy.admin.roles.orgAdmin}</option>
            </Select>
            <p className="text-sm text-subtle">
              {role === "area_viewer" ? mCopy.roleViewerDesc : mCopy.roleAdminDesc}
            </p>
            {role === "area_viewer" && (
              <Select
                label={mCopy.areaLabel}
                id="grant-area"
                required
                value={area}
                onChange={(e) => setArea(e.target.value)}
              >
                <option value="">{mCopy.areaPlaceholder}</option>
                <AreaOptions />
              </Select>
            )}
            <div>
              <Button type="submit" variant="primary" size="sm" disabled={busy || (role === "area_viewer" && !area)}>
                {mCopy.grantSubmit}
              </Button>
            </div>
          </div>
        </form>
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex justify-end border-t border-line pt-4">
          <Button onClick={onClose}>{copy.common.done}</Button>
        </div>
      </div>
    </Modal>
  );
}

export function AdminUsers() {
  const { me } = useAuth();
  const [version, setVersion] = useState(0);
  const st = useAsync(() => adminApi.users(), [version]);
  const reload = () => setVersion((v) => v + 1);
  // One-time secrets (generated passwords) live only here, in state; dismissing drops them.
  const [secret, setSecret] = useState<Secret | null>(null);
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<AdminUser | null>(null);
  const [toggling, setToggling] = useState<AdminUser | null>(null);
  const [accessFor, setAccessFor] = useState<number | null>(null);

  useEffect(() => {
    document.title = `${copy.admin.users.pageTitle} · ${copy.brand.full}`;
  }, []);

  const uCopy = copy.admin.users;

  const actions = (u: AdminUser, align = "") => (
    <div className={cx("flex flex-wrap gap-2", align)}>
      <Button size="sm" onClick={() => setAccessFor(u.id)} aria-label={uCopy.actions.accessAria(u.email)}>
        {uCopy.actions.access}
      </Button>
      <Button size="sm" onClick={() => setResetting(u)} aria-label={uCopy.actions.resetPasswordAria(u.email)}>
        {uCopy.actions.resetPassword}
      </Button>
      <Button
        size="sm"
        disabled={me?.id === u.id}
        aria-describedby={me?.id === u.id ? "self-deactivate-note" : undefined}
        onClick={() => setToggling(u)}
        aria-label={uCopy.actions.toggleAria(u.active, u.email)}
      >
        {u.active ? copy.common.deactivate : copy.common.activate}
      </Button>
    </div>
  );

  const membershipText = (m: AdminUser["memberships"][number]) =>
    m.role === "org_admin"
      ? copy.admin.roles.orgAdmin
      : copy.admin.roles.viewerTag(m.area_name ?? copy.admin.roles.areaFallback);

  return (
    <>
      <PageHeader
        crumbs={[{ label: copy.admin.crumbRoot }, { label: uCopy.crumb }]}
        title={uCopy.title}
        lead={uCopy.lead}
        stamp={uCopy.stamp}
      >
        <Button variant="primary" onClick={() => setCreating(true)}>
          {uCopy.createAction}
        </Button>
      </PageHeader>

      <p id="self-deactivate-note" className="sr-only">
        {uCopy.selfDeactivateNote}
      </p>
      {secret && (
        <div className="mb-6">
          <OneTimeSecret
            title={secret.title}
            announcement={uCopy.secretAnnouncement}
            secret={secret.value}
            onDismiss={() => setSecret(null)}
          />
        </div>
      )}
      {st.loading && !st.data && (
        <LogbookLoading label={uCopy.loadingLabel} caption={uCopy.loadingCaption} />
      )}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && st.data.length === 0 && (
        <LogbookEmpty tag={uCopy.emptyTag} title={uCopy.emptyTitle} artCaption={uCopy.emptyArtCaption}>
          {uCopy.emptyBody}
        </LogbookEmpty>
      )}
      {st.data && st.data.length > 0 && (
        <section aria-labelledby="admin-users-list">
          <div className="mb-4 flex flex-wrap items-baseline justify-between gap-4">
            <h2 id="admin-users-list" className="eyebrow text-ink">
              {uCopy.listHeading}
            </h2>
            <span className="font-mono text-xs font-semibold tabular-nums text-subtle">
              {uCopy.countLabel(st.data.length)}
            </span>
          </div>

          <div className="box hidden overflow-x-auto md:block">
            <table className="data-table min-w-[52rem]">
              <caption className="sr-only">{uCopy.tableCaption}</caption>
              <thead>
                <tr>
                  <th scope="col">{uCopy.columns.email}</th>
                  <th scope="col">{uCopy.columns.status}</th>
                  <th scope="col">{uCopy.columns.access}</th>
                  <th scope="col" className="text-right">
                    <span className="sr-only">{uCopy.columns.actions}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {st.data.map((u) => (
                  <tr key={u.id} className="hover:bg-surface">
                    <th scope="row" className="break-all font-mono text-xs font-semibold text-ink">
                      {u.email}
                      {me?.id === u.id && (
                        <span className="ml-1.5 whitespace-nowrap font-sans font-normal text-subtle">
                          {uCopy.youMarker}
                        </span>
                      )}
                    </th>
                    <td>
                      <Tag muted={!u.active}>{u.active ? copy.common.active : copy.common.inactive}</Tag>
                    </td>
                    <td className="text-sm text-ink">
                      {u.memberships.length === 0 ? (
                        <span className="text-subtle">{copy.common.none}</span>
                      ) : (
                        <ul className="m-0 list-none p-0">
                          {u.memberships.map((m) => (
                            <li key={m.id}>{membershipText(m)}</li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td>{actions(u, "justify-end")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="border border-ink bg-paper md:hidden">
            <div className="ruler-x" aria-hidden="true" />
            <ul className="m-0 list-none divide-y divide-ink/25 p-0">
              {st.data.map((u, idx) => (
                <li key={u.id} className="flex flex-col gap-3 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono text-xs font-semibold tabular-nums text-subtle">
                      {fmtIdx(idx)}
                      {me?.id === u.id ? ` · ${uCopy.youMarker}` : ""}
                    </span>
                    <Tag muted={!u.active}>{u.active ? copy.common.active : copy.common.inactive}</Tag>
                  </div>
                  <p className="break-all font-mono text-sm font-semibold text-ink">{u.email}</p>
                  <div className="border-t border-line pt-2.5">
                    <p className="eyebrow">{uCopy.columns.access}</p>
                    <p className="mt-1 text-sm text-subtle">
                      {u.memberships.length === 0
                        ? uCopy.noAccess
                        : u.memberships.map(membershipText).join(", ")}
                    </p>
                  </div>
                  <div className="pt-1">{actions(u)}</div>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      {creating && (
        <CreateUser
          onClose={() => setCreating(false)}
          onDone={(s) => {
            if (s) setSecret(s);
            reload();
          }}
        />
      )}
      {resetting && (
        <ResetPassword
          user={resetting}
          onClose={() => setResetting(null)}
          onDone={(s) => {
            setSecret(s);
            reload();
          }}
        />
      )}
      {toggling && (
        <ConfirmModal
          title={
            toggling.active
              ? uCopy.toggleModal.deactivateTitle(toggling.email)
              : uCopy.toggleModal.activateTitle(toggling.email)
          }
          confirmLabel={toggling.active ? copy.common.deactivate : copy.common.activate}
          onClose={() => setToggling(null)}
          onConfirm={async () => {
            await adminApi.patchUser(toggling.id, { active: !toggling.active });
            reload();
          }}
        >
          <p>{toggling.active ? uCopy.toggleModal.deactivateBody : uCopy.toggleModal.activateBody}</p>
        </ConfirmModal>
      )}
      {accessFor !== null && st.data && (
        <ManageAccess userId={accessFor} users={st.data} onClose={() => setAccessFor(null)} onChanged={reload} />
      )}
    </>
  );
}
