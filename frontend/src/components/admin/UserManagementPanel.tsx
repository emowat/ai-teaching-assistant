import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  createAdminUser,
  listAdminUsers,
  updateAdminUser,
  type AdminUser,
  type AppPrimaryRole,
  type SectionMembershipStatus,
  type UserStatus,
} from "../../api/adminUsersApi";
import { Avatar, Btn, Card, Tag } from "../../design/atoms";
import { D } from "../../design/tokens";

interface UserManagementPanelProps {
  accessToken: string;
}

interface CreateDraft {
  email: string;
  display_name: string;
  primary_role: AppPrimaryRole;
  status: UserStatus;
}

interface EditDraft {
  display_name: string;
  primary_role: AppPrimaryRole;
  status: UserStatus;
}

const ROLE_OPTIONS: AppPrimaryRole[] = ["admin", "professor", "student"];
const STATUS_OPTIONS: UserStatus[] = ["invited", "active", "disabled"];

function emptyCreateDraft(): CreateDraft {
  return {
    email: "",
    display_name: "",
    primary_role: "professor",
    status: "invited",
  };
}

function emptyEditDraft(): EditDraft {
  return {
    display_name: "",
    primary_role: "professor",
    status: "active",
  };
}

function membershipStatusColor(status: SectionMembershipStatus): string {
  if (status === "active") return D.green;
  if (status === "invited") return D.orange;
  return D.muted;
}

export function UserManagementPanel({ accessToken }: UserManagementPanelProps) {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [formStatus, setFormStatus] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [savingUserId, setSavingUserId] = useState<string | null>(null);
  const [roleFilter, setRoleFilter] = useState<AppPrimaryRole | "all">("all");
  const [statusFilter, setStatusFilter] = useState<UserStatus | "all">("all");
  const [createDraft, setCreateDraft] = useState<CreateDraft>(emptyCreateDraft());
  const [editDraft, setEditDraft] = useState<EditDraft>(emptyEditDraft());
  const selectedUserIdRef = useRef<string | null>(null);

  const selectedUser = users.find((user) => user.user_id === selectedUserId) ?? null;

  const applySelectedUser = useCallback((user: AdminUser | null) => {
    selectedUserIdRef.current = user?.user_id ?? null;
    setSelectedUserId(user?.user_id ?? null);
    if (user === null) {
      setEditDraft(emptyEditDraft());
      return;
    }

    setEditDraft({
      display_name: user.display_name,
      primary_role: user.primary_role,
      status: user.status,
    });
  }, []);

  const syncUsers = useCallback((nextUsers: AdminUser[]) => {
    setUsers(nextUsers);
    const nextSelectedUser =
      nextUsers.find((user) => user.user_id === selectedUserIdRef.current) ?? nextUsers[0] ?? null;
    applySelectedUser(nextSelectedUser);
  }, [applySelectedUser]);

  const upsertUser = (nextUser: AdminUser) => {
    setUsers((current) => {
      const next = current.filter((user) => user.user_id !== nextUser.user_id);
      next.push(nextUser);
      next.sort((left, right) => left.email.localeCompare(right.email));
      return next;
    });
  };

  useEffect(() => {
    let cancelled = false;

    void listAdminUsers(accessToken)
      .then((nextUsers) => {
        if (cancelled) return;
        syncUsers(nextUsers);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setUsers([]);
          applySelectedUser(null);
          setFormError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken, applySelectedUser, syncUsers]);

  const handleRefreshUsers = async () => {
    setRefreshing(true);
    setFormError(null);
    setFormStatus(null);

    try {
      const nextUsers = await listAdminUsers(accessToken);
      syncUsers(nextUsers);
      setFormStatus(`Refreshed ${nextUsers.length} users.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to refresh users.");
    } finally {
      setRefreshing(false);
    }
  };

  const filteredUsers = useMemo(
    () =>
      users.filter((user) => {
        const roleOk = roleFilter === "all" || user.primary_role === roleFilter;
        const statusOk = statusFilter === "all" || user.status === statusFilter;
        return roleOk && statusOk;
      }),
    [roleFilter, statusFilter, users]
  );

  const activeCount = users.filter((user) => user.status === "active").length;
  const invitedCount = users.filter((user) => user.status === "invited").length;

  const handleCreateUser = async () => {
    setCreating(true);
    setFormError(null);
    setFormStatus(null);

    try {
      if (!createDraft.email.trim()) {
        throw new Error("Email is required.");
      }
      if (!createDraft.display_name.trim()) {
        throw new Error("Display name is required.");
      }

      const created = await createAdminUser(accessToken, {
        email: createDraft.email.trim(),
        display_name: createDraft.display_name.trim(),
        primary_role: createDraft.primary_role,
        status: createDraft.status,
      });
      upsertUser(created);
      applySelectedUser(created);
      setCreateDraft(emptyCreateDraft());
      setFormStatus(`Created ${created.email}.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to create user.");
    } finally {
      setCreating(false);
    }
  };

  const handleSaveUser = async () => {
    if (selectedUser === null) {
      return;
    }

    setSavingUserId(selectedUser.user_id);
    setFormError(null);
    setFormStatus(null);

    try {
      if (!editDraft.display_name.trim()) {
        throw new Error("Display name is required.");
      }

      const updated = await updateAdminUser(selectedUser.user_id, accessToken, {
        display_name: editDraft.display_name.trim(),
        primary_role: editDraft.primary_role,
        status: editDraft.status,
      });
      upsertUser(updated);
      applySelectedUser(updated);
      setFormStatus(`Updated ${updated.email}.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to update user.");
    } finally {
      setSavingUserId(null);
    }
  };

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <Card style={{ display: "grid", gap: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>Users</div>
            <div style={{ fontSize: 12, color: D.muted, marginTop: 4 }}>
              Aurora-backed application users and their section memberships.
            </div>
            <div style={{ fontSize: 11, color: D.dim, marginTop: 6, lineHeight: 1.4 }}>
              Invite users in Aurora first. On first Cognito sign-in, the app claims the Aurora record by email
              and stores the Cognito `sub`.
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Tag color={D.blue}>{users.length} total</Tag>
            <Tag color={D.green}>{activeCount} active</Tag>
            <Tag color={D.orange}>{invitedCount} invited</Tag>
            <Btn small variant="ghost" onClick={() => void handleRefreshUsers()} disabled={loading || refreshing}>
              {refreshing ? "Refreshing..." : "Refresh"}
            </Btn>
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <label style={{ display: "grid", gap: 5, minWidth: 180 }}>
            <span style={{ fontSize: 12, color: D.muted }}>Role filter</span>
            <select
              value={roleFilter}
              onChange={(event) => setRoleFilter(event.target.value as AppPrimaryRole | "all")}
              style={{
                background: D.bg,
                color: D.text,
                border: `1px solid ${D.border}`,
                borderRadius: 8,
                padding: "10px 12px",
              }}
            >
              <option value="all">All roles</option>
              {ROLE_OPTIONS.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "grid", gap: 5, minWidth: 180 }}>
            <span style={{ fontSize: 12, color: D.muted }}>Status filter</span>
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as UserStatus | "all")}
              style={{
                background: D.bg,
                color: D.text,
                border: `1px solid ${D.border}`,
                borderRadius: 8,
                padding: "10px 12px",
              }}
            >
              <option value="all">All statuses</option>
              {STATUS_OPTIONS.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
        </div>
        {loading && <div style={{ fontSize: 12, color: D.muted }}>Loading users...</div>}
        {formError && <div style={{ fontSize: 12, color: D.red }}>{formError}</div>}
        {formStatus && <div style={{ fontSize: 12, color: D.green }}>{formStatus}</div>}
      </Card>

      <Card style={{ display: "grid", gap: 10 }}>
        <label style={{ display: "grid", gap: 5 }}>
          <span style={{ fontSize: 13, fontWeight: 500 }}>Select User to Manage</span>
          <select
            value={selectedUserId ?? "NEW"}
            onChange={(e) => {
              if (e.target.value === "NEW") {
                applySelectedUser(null);
              } else {
                const user = filteredUsers.find((u) => u.user_id === e.target.value);
                if (user) applySelectedUser(user);
              }
            }}
            style={{
              background: D.bg,
              color: D.text,
              border: `1px solid ${D.border}`,
              borderRadius: 8,
              padding: "8px 12px",
              fontSize: 14,
            }}
          >
            <option value="NEW">-- Invite New User --</option>
            {filteredUsers.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.display_name || u.email} ({u.email})
              </option>
            ))}
          </select>
        </label>
      </Card>

      {selectedUser === null ? (
        <Card style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>Invite user</div>
            <Tag color={D.muted}>new</Tag>
          </div>
          <div style={{ display: "grid", gap: 10 }}>
            <label style={{ display: "grid", gap: 5 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Email</span>
              <input
                value={createDraft.email}
                onChange={(event) =>
                  setCreateDraft((current) => ({ ...current, email: event.target.value }))
                }
                placeholder="student@example.edu"
                style={{
                  background: D.bg,
                  color: D.text,
                  border: `1px solid ${D.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                }}
              />
            </label>
            <label style={{ display: "grid", gap: 5 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Display name</span>
              <input
                value={createDraft.display_name}
                onChange={(event) =>
                  setCreateDraft((current) => ({ ...current, display_name: event.target.value }))
                }
                placeholder="Ada Lovelace"
                style={{
                  background: D.bg,
                  color: D.text,
                  border: `1px solid ${D.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                }}
              />
            </label>
            <label style={{ display: "grid", gap: 5 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Primary role</span>
              <select
                value={createDraft.primary_role}
                onChange={(event) =>
                  setCreateDraft((current) => ({
                    ...current,
                    primary_role: event.target.value as AppPrimaryRole,
                  }))
                }
                style={{
                  background: D.bg,
                  color: D.text,
                  border: `1px solid ${D.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                }}
              >
                {ROLE_OPTIONS.map((role) => (
                  <option key={role} value={role}>
                    {role}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ display: "grid", gap: 5 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Status</span>
              <select
                value={createDraft.status}
                onChange={(event) =>
                  setCreateDraft((current) => ({
                    ...current,
                    status: event.target.value as UserStatus,
                  }))
                }
                style={{
                  background: D.bg,
                  color: D.text,
                  border: `1px solid ${D.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                }}
              >
                {STATUS_OPTIONS.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
            </label>
            <div>
              <Btn small onClick={() => void handleCreateUser()} disabled={creating || loading}>
                {creating ? "Creating..." : "Invite user"}
              </Btn>
            </div>
          </div>
        </Card>
      ) : (
        <Card style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>
              Manage {selectedUser.email}
            </div>
            <Tag color={membershipStatusColor(selectedUser.status)}>{selectedUser.status}</Tag>
          </div>
          <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <Avatar name={selectedUser.display_name || selectedUser.email} />
                <div style={{ display: "grid", gap: 2 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>{selectedUser.display_name}</div>
                  <div style={{ fontSize: 12, color: D.muted }}>{selectedUser.email}</div>
                  <div style={{ fontSize: 11, color: D.dim }}>
                    Cognito claim: {selectedUser.cognito_sub ?? "unclaimed"}
                  </div>
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
                <label style={{ display: "grid", gap: 5 }}>
                  <span style={{ fontSize: 12, color: D.muted }}>Display name</span>
                  <input
                    value={editDraft.display_name}
                    onChange={(event) =>
                      setEditDraft((current) => ({ ...current, display_name: event.target.value }))
                    }
                    style={{
                      background: D.bg,
                      color: D.text,
                      border: `1px solid ${D.border}`,
                      borderRadius: 8,
                      padding: "10px 12px",
                    }}
                  />
                </label>
                <label style={{ display: "grid", gap: 5 }}>
                  <span style={{ fontSize: 12, color: D.muted }}>Primary role</span>
                  <select
                    value={editDraft.primary_role}
                    onChange={(event) =>
                      setEditDraft((current) => ({
                        ...current,
                        primary_role: event.target.value as AppPrimaryRole,
                      }))
                    }
                    style={{
                      background: D.bg,
                      color: D.text,
                      border: `1px solid ${D.border}`,
                      borderRadius: 8,
                      padding: "10px 12px",
                    }}
                  >
                    {ROLE_OPTIONS.map((role) => (
                      <option key={role} value={role}>
                        {role}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={{ display: "grid", gap: 5 }}>
                  <span style={{ fontSize: 12, color: D.muted }}>Status</span>
                  <select
                    value={editDraft.status}
                    onChange={(event) =>
                      setEditDraft((current) => ({
                        ...current,
                        status: event.target.value as UserStatus,
                      }))
                    }
                    style={{
                      background: D.bg,
                      color: D.text,
                      border: `1px solid ${D.border}`,
                      borderRadius: 8,
                      padding: "10px 12px",
                    }}
                  >
                    {STATUS_OPTIONS.map((status) => (
                      <option key={status} value={status}>
                        {status}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <Btn
                  small
                  onClick={() => void handleSaveUser()}
                  disabled={savingUserId === selectedUser.user_id || loading}
                >
                  {savingUserId === selectedUser.user_id ? "Saving..." : "Save user"}
                </Btn>
                <Tag color={D.blue}>{selectedUser.section_memberships.length} memberships</Tag>
              </div>
              <div style={{ display: "grid", gap: 8 }}>
                <div style={{ fontSize: 12, color: D.muted }}>Memberships</div>
                {selectedUser.section_memberships.length === 0 ? (
                  <div style={{ fontSize: 12, color: D.dim }}>No section memberships yet.</div>
                ) : (
                  selectedUser.section_memberships.map((membership) => (
                    <Card
                      key={`${membership.section_id}-${membership.role_in_section}`}
                      style={{ display: "grid", gap: 4, padding: 12 }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                        <div style={{ fontSize: 13, fontWeight: 600 }}>
                          {membership.section_display_name}
                        </div>
                        <Tag color={membershipStatusColor(membership.status)}>{membership.status}</Tag>
                      </div>
                      <div style={{ fontSize: 11, color: D.muted }}>
                        {membership.course_id} · {membership.course_display_name}
                      </div>
                      <div style={{ fontSize: 11, color: D.dim }}>
                        {membership.role_in_section} · created {membership.created_at}
                      </div>
                    </Card>
                  ))
                )}
              </div>
            </div>

        </Card>
      )}
    </div>
  );
}
