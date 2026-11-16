import { useState } from "react";
import type { FormEvent } from "react";
import { adminApi } from "../../adminApi";
import type { AdminUser, Role } from "../../adminApi";
import { useAuth } from "../../auth";
import { ConfirmModal, Modal, OneTimeSecret } from "../../dialogs";
import { generatePassword } from "../../password";
import { Button, cx, EmptyState, ErrorBox, Field, Loading, PageHeader, Select, Tag, useAsync } from "../../ui";
import { indent, orderTree } from "./tree";

type Secret = { title: string; value: string };

const roleLabel = (r: string) => (r === "org_admin" ? "Organization admin" : "Area viewer");

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
      onDone(generated ? { title: `Initial password for ${email.trim()}`, value: password } : null);
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Something went wrong.";
      if (userId !== null) {
        // the user exists but the access step failed: say so, and do not offer to create it again
        onDone(generated ? { title: `Initial password for ${email.trim()}`, value: password } : null);
        setError(`The user was created, but granting access failed: ${msg} Use "Manage access" on the list.`);
        setBusy(false);
        return;
      }
      setError(msg);
      setBusy(false);
    }
  }

  return (
    <Modal title="Create user" onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-6">
        <Field label="Email" id="user-email" type="email" required maxLength={254} value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
        <div className="flex flex-col gap-2">
          <Field
            label="Initial password"
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
            hint="At least 12 characters. Generate one if you prefer; it is shown here and again once after you create the user."
          />
          <div>
            <Button
              size="sm"
              onClick={() => {
                setPassword(generatePassword());
                setGenerated(true);
              }}
            >
              Generate
            </Button>
          </div>
        </div>
        <Select label="Access" id="user-access" value={access} onChange={(e) => setAccess(e.target.value)}>
          <option value="none">No access yet</option>
          <option value="admin">Organization admin (all areas and administration)</option>
          {areas.data &&
            orderTree(areas.data).map((a) => (
              <option key={a.id} value={`area:${a.id}`}>
                Area viewer: {indent(a.depth)}
                {a.name}
              </option>
            ))}
        </Select>
        <p className="text-sm text-subtle">Access to an area includes its sub-areas.</p>
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex flex-wrap justify-end gap-3">
          <Button onClick={onClose} disabled={busy}>
            {createdId !== null ? "Close" : "Cancel"}
          </Button>
          {createdId === null && (
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? "Creating…" : "Create user"}
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
      title={`Reset password for ${user.email}?`}
      confirmLabel="Reset password"
      onClose={onClose}
      onConfirm={async () => {
        await adminApi.patchUser(user.id, { password });
        onDone({ title: `New password for ${user.email}`, value: password });
      }}
    >
      <p>
        A new random password will be set and shown once. This ends all of the user's sessions, so they must log in again.
      </p>
    </ConfirmModal>
  );
}

function ManageAccess({ userId, users, onClose, onChanged }: { userId: number; users: AdminUser[]; onClose: () => void; onChanged: () => void }) {
  const { me } = useAuth();
  const user = users.find((u) => u.id === userId);
  const [role, setRole] = useState<Role>("area_viewer");
  const [area, setArea] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<number | null>(null);
  if (!user) return null;

  async function grant(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await adminApi.grant(userId, role, role === "org_admin" ? null : Number(area));
      onChanged();
      setArea("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
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
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title={`Access for ${user.email}`} onClose={onClose} wide>
      <div className="flex flex-col gap-6">
        <p className="text-subtle">Access to an area includes its sub-areas, never the areas above it.</p>
        {user.memberships.length === 0 ? (
          <p className="font-semibold">No access yet.</p>
        ) : (
          <ul className="m-0 list-none p-0">
            {user.memberships.map((m) => {
              const own = me?.id === user.id && m.role === "org_admin";
              return (
                <li key={m.id} className="rule-t flex flex-wrap items-center justify-between gap-3 py-3 last:border-b last:border-ink">
                  <span>
                    <span className="font-bold">{m.role === "org_admin" ? "Organization admin" : m.area_name}</span>
                    {m.role !== "org_admin" && <span className="text-subtle"> · {roleLabel(m.role)}</span>}
                  </span>
                  {confirming === m.id ? (
                    <span className="flex items-center gap-2">
                      <Button size="sm" variant="dark" disabled={busy} onClick={() => revoke(m.id)}>
                        Confirm revoke
                      </Button>
                      <Button size="sm" disabled={busy} onClick={() => setConfirming(null)}>
                        Cancel
                      </Button>
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      disabled={busy || own}
                      aria-describedby={own ? `own-admin-note-${m.id}` : undefined}
                      onClick={() => setConfirming(m.id)}
                      aria-label={`Revoke ${m.role === "org_admin" ? "organization admin" : m.area_name} access`}
                    >
                      Revoke
                    </Button>
                  )}
                  {own && (
                    <p id={`own-admin-note-${m.id}`} className="w-full text-sm text-subtle">
                      You cannot remove your own admin access.
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        <form onSubmit={grant} className="box flex flex-col gap-4 p-4">
          <p className="font-extrabold">Grant access</p>
          <Select label="Role" id="grant-role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="area_viewer">Area viewer</option>
            <option value="org_admin">Organization admin</option>
          </Select>
          <p className="text-sm text-subtle">
            {role === "area_viewer" ? "Reads the reports of one area and its sub-areas." : "Reads every area and uses the administration pages."}
          </p>
          {role === "area_viewer" && (
            <Select label="Area" id="grant-area" required value={area} onChange={(e) => setArea(e.target.value)}>
              <option value="">Choose an area…</option>
              <AreaOptions />
            </Select>
          )}
          <div>
            <Button type="submit" variant="primary" size="sm" disabled={busy || (role === "area_viewer" && !area)}>
              Grant access
            </Button>
          </div>
        </form>
        {error && <ErrorBox>{error}</ErrorBox>}
        <div className="flex justify-end">
          <Button onClick={onClose}>Done</Button>
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

  const actions = (u: AdminUser, align = "") => (
    <div className={cx("flex flex-wrap gap-2", align)}>
      <Button size="sm" onClick={() => setAccessFor(u.id)} aria-label={`Manage access for ${u.email}`}>
        Access
      </Button>
      <Button size="sm" onClick={() => setResetting(u)} aria-label={`Reset password for ${u.email}`}>
        Reset password
      </Button>
      <Button
        size="sm"
        disabled={me?.id === u.id}
        aria-describedby={me?.id === u.id ? "self-deactivate-note" : undefined}
        onClick={() => setToggling(u)}
        aria-label={`${u.active ? "Deactivate" : "Activate"} ${u.email}`}
      >
        {u.active ? "Deactivate" : "Activate"}
      </Button>
    </div>
  );

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Administration" }, { label: "Users" }]}
        title="Users"
        lead="People who can log in. Their access decides which agents' reports they can read."
      >
        <Button variant="primary" onClick={() => setCreating(true)}>
          Create user
        </Button>
      </PageHeader>

      <p id="self-deactivate-note" className="sr-only">
        You cannot deactivate your own account.
      </p>
      {secret && (
        <div className="mb-6">
          <OneTimeSecret
            title={secret.title}
            announcement="Password generated. Shown once; store it now."
            secret={secret.value}
            onDismiss={() => setSecret(null)}
          />
        </div>
      )}
      {st.loading && !st.data && <Loading />}
      {st.error && <ErrorBox>{st.error}</ErrorBox>}
      {st.data && st.data.length === 0 && <EmptyState title="No users yet." />}
      {st.data && st.data.length > 0 && (
        <div className="box hidden overflow-x-auto md:block">
          <table className="data-table min-w-[52rem]">
            <caption className="sr-only">Users</caption>
            <thead>
              <tr>
                <th scope="col">Email</th>
                <th scope="col">Status</th>
                <th scope="col">Access</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {st.data.map((u) => (
                <tr key={u.id}>
                  <th scope="row" className="break-all">
                    {u.email}
                    {me?.id === u.id && <span className="whitespace-nowrap font-normal text-subtle"> (you)</span>}
                  </th>
                  <td>{u.active ? <Tag>Active</Tag> : <Tag>Inactive</Tag>}</td>
                  <td>
                    {u.memberships.length === 0 ? (
                      <span className="text-subtle">None</span>
                    ) : (
                      <ul className="m-0 list-none p-0">
                        {u.memberships.map((m) => (
                          <li key={m.id}>{m.role === "org_admin" ? "Organization admin" : `${m.area_name} (viewer)`}</li>
                        ))}
                      </ul>
                    )}
                  </td>
                  <td>
                    {actions(u, "justify-end")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {st.data && st.data.length > 0 && (
        <ul className="m-0 list-none p-0 md:hidden">
          {st.data.map((u) => (
            <li key={u.id} className="rule-t flex flex-col gap-3 py-5 last:border-b last:border-ink">
              <p className="break-all font-bold">
                {u.email}
                {me?.id === u.id && <span className="font-normal text-subtle"> (you)</span>}
              </p>
              <p className="flex flex-wrap items-center gap-3 text-sm">
                {u.active ? <Tag>Active</Tag> : <Tag>Inactive</Tag>}
                <span className="text-subtle">
                  {u.memberships.length === 0
                    ? "No access"
                    : u.memberships.map((m) => (m.role === "org_admin" ? "Organization admin" : `${m.area_name} (viewer)`)).join(", ")}
                </span>
              </p>
              {actions(u)}
            </li>
          ))}
        </ul>
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
          title={toggling.active ? `Deactivate ${toggling.email}?` : `Activate ${toggling.email}?`}
          confirmLabel={toggling.active ? "Deactivate" : "Activate"}
          onClose={() => setToggling(null)}
          onConfirm={async () => {
            await adminApi.patchUser(toggling.id, { active: !toggling.active });
            reload();
          }}
        >
          <p>
            {toggling.active
              ? "The user will not be able to log in, and all of their sessions end now."
              : "The user will be able to log in again with their current password."}
          </p>
        </ConfirmModal>
      )}
      {accessFor !== null && st.data && (
        <ManageAccess userId={accessFor} users={st.data} onClose={() => setAccessFor(null)} onChanged={reload} />
      )}
    </>
  );
}
