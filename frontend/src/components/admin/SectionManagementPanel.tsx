import { useEffect, useState } from "react";
import {
  createAdminSection,
  createAdminSectionMembership,
  listAdminSections,
  updateAdminSection,
  updateAdminSectionMembership,
  type AdminSection,
} from "../../api/adminSectionsApi";
import {
  listAdminUsers,
  type AdminUser,
  type SectionMembershipRole,
  type SectionMembershipStatus,
} from "../../api/adminUsersApi";
import { Avatar, Btn, Card, Tag } from "../../design/atoms";
import { D } from "../../design/tokens";

interface SectionManagementPanelProps {
  accessToken: string;
}

interface CreateDraft {
  section_id: string;
  course_id: string;
  display_name: string;
  term: string;
  is_active: boolean;
}

interface EditDraft {
  display_name: string;
  term: string;
  is_active: boolean;
}

interface MembershipCreateDraft {
  user_id: string;
  role_in_section: SectionMembershipRole;
  status: SectionMembershipStatus;
}

interface MembershipEditDraft {
  role_in_section: SectionMembershipRole;
  status: SectionMembershipStatus;
}

const ROLE_OPTIONS: SectionMembershipRole[] = ["professor", "ta", "student"];
const STATUS_OPTIONS: SectionMembershipStatus[] = ["invited", "active", "dropped", "disabled"];

function emptyCreateDraft(): CreateDraft {
  return {
    section_id: "",
    course_id: "",
    display_name: "",
    term: "",
    is_active: true,
  };
}

function emptyEditDraft(): EditDraft {
  return {
    display_name: "",
    term: "",
    is_active: true,
  };
}

function emptyMembershipCreateDraft(users: AdminUser[]): MembershipCreateDraft {
  return {
    user_id: users[0]?.user_id ?? "",
    role_in_section: "student",
    status: "active",
  };
}

function emptyMembershipEditDraft(): MembershipEditDraft {
  return {
    role_in_section: "student",
    status: "active",
  };
}

export function SectionManagementPanel({ accessToken }: SectionManagementPanelProps) {
  const [sections, setSections] = useState<AdminSection[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedSectionId, setSelectedSectionId] = useState<string | null>(null);
  const [selectedMembershipUserId, setSelectedMembershipUserId] = useState<string | null>(null);
  const [createDraft, setCreateDraft] = useState<CreateDraft>(emptyCreateDraft());
  const [editDraft, setEditDraft] = useState<EditDraft>(emptyEditDraft());
  const [membershipCreateDraft, setMembershipCreateDraft] = useState<MembershipCreateDraft>(
    emptyMembershipCreateDraft([])
  );
  const [membershipEditDraft, setMembershipEditDraft] = useState<MembershipEditDraft>(
    emptyMembershipEditDraft()
  );
  const [creating, setCreating] = useState(false);
  const [savingSectionId, setSavingSectionId] = useState<string | null>(null);
  const [savingMembership, setSavingMembership] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formStatus, setFormStatus] = useState<string | null>(null);

  const selectedSection = sections.find((section) => section.section_id === selectedSectionId) ?? null;
  const selectedMembership =
    selectedSection?.memberships.find((membership) => membership.user_id === selectedMembershipUserId) ??
    null;

  const upsertSection = (nextSection: AdminSection) => {
    setSections((current) => {
      const next = current.filter((section) => section.section_id !== nextSection.section_id);
      next.push(nextSection);
      next.sort((left, right) => left.section_id.localeCompare(right.section_id));
      return next;
    });
  };

  const applySelectedSection = (section: AdminSection | null, nextUsers: AdminUser[] = users) => {
    setSelectedSectionId(section?.section_id ?? null);
    const firstMembershipUserId = section?.memberships[0]?.user_id ?? null;
    setSelectedMembershipUserId(firstMembershipUserId);

    if (section === null) {
      setEditDraft(emptyEditDraft());
      setMembershipCreateDraft(emptyMembershipCreateDraft(nextUsers));
      setMembershipEditDraft(emptyMembershipEditDraft());
      return;
    }

    setEditDraft({
      display_name: section.display_name,
      term: section.term,
      is_active: section.is_active,
    });
    setMembershipCreateDraft((current) => ({
      ...current,
      user_id: current.user_id || nextUsers[0]?.user_id || "",
    }));
    setMembershipEditDraft(
      section.memberships[0]
        ? {
            role_in_section: section.memberships[0].role_in_section,
            status: section.memberships[0].status,
          }
        : emptyMembershipEditDraft()
    );
  };

  useEffect(() => {
    let cancelled = false;

    void Promise.all([listAdminSections(accessToken), listAdminUsers(accessToken)])
      .then(([nextSections, nextUsers]) => {
        if (cancelled) return;
        setSections(nextSections);
        setUsers(nextUsers);
        setMembershipCreateDraft(emptyMembershipCreateDraft(nextUsers));
        applySelectedSection(nextSections[0] ?? null, nextUsers);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setSections([]);
          setUsers([]);
          applySelectedSection(null, []);
          setFormError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  const activeCount = sections.filter((section) => section.is_active).length;
  const membershipCount = sections.reduce((total, section) => total + section.memberships.length, 0);

  const handleCreateSection = async () => {
    setCreating(true);
    setFormError(null);
    setFormStatus(null);

    try {
      if (!createDraft.section_id.trim()) throw new Error("Section ID is required.");
      if (!createDraft.course_id.trim()) throw new Error("Course ID is required.");
      if (!createDraft.display_name.trim()) throw new Error("Display name is required.");

      const created = await createAdminSection(accessToken, {
        section_id: createDraft.section_id.trim(),
        course_id: createDraft.course_id.trim(),
        display_name: createDraft.display_name.trim(),
        term: createDraft.term.trim(),
        is_active: createDraft.is_active,
      });
      upsertSection(created);
      applySelectedSection(created);
      setCreateDraft(emptyCreateDraft());
      setFormStatus(`Created ${created.section_id}.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to create section.");
    } finally {
      setCreating(false);
    }
  };

  const handleSaveSection = async () => {
    if (selectedSection === null) {
      return;
    }

    setSavingSectionId(selectedSection.section_id);
    setFormError(null);
    setFormStatus(null);

    try {
      if (!editDraft.display_name.trim()) throw new Error("Display name is required.");

      const updated = await updateAdminSection(selectedSection.section_id, accessToken, {
        display_name: editDraft.display_name.trim(),
        term: editDraft.term.trim(),
        is_active: editDraft.is_active,
      });
      upsertSection(updated);
      applySelectedSection(updated);
      setFormStatus(`Updated ${updated.section_id}.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to update section.");
    } finally {
      setSavingSectionId(null);
    }
  };

  const handleCreateMembership = async () => {
    if (selectedSection === null) {
      return;
    }

    setSavingMembership(true);
    setFormError(null);
    setFormStatus(null);

    try {
      if (!membershipCreateDraft.user_id.trim()) throw new Error("Select a user.");

      const updated = await createAdminSectionMembership(selectedSection.section_id, accessToken, {
        user_id: membershipCreateDraft.user_id.trim(),
        role_in_section: membershipCreateDraft.role_in_section,
        status: membershipCreateDraft.status,
      });
      upsertSection(updated);
      applySelectedSection(updated);
      setFormStatus(`Added membership to ${updated.section_id}.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to add membership.");
    } finally {
      setSavingMembership(false);
    }
  };

  const handleSaveMembership = async () => {
    if (selectedSection === null || selectedMembershipUserId === null) {
      return;
    }

    setSavingMembership(true);
    setFormError(null);
    setFormStatus(null);

    try {
      const updated = await updateAdminSectionMembership(
        selectedSection.section_id,
        selectedMembershipUserId,
        accessToken,
        {
          role_in_section: membershipEditDraft.role_in_section,
          status: membershipEditDraft.status,
        }
      );
      upsertSection(updated);
      applySelectedSection(updated);
      setFormStatus(`Updated membership for ${selectedMembershipUserId}.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to update membership.");
    } finally {
      setSavingMembership(false);
    }
  };

  const selectMembership = (section: AdminSection, userId: string) => {
    const membership = section.memberships.find((entry) => entry.user_id === userId);
    if (!membership) {
      return;
    }
    setSelectedSectionId(section.section_id);
    setSelectedMembershipUserId(userId);
    setMembershipEditDraft({
      role_in_section: membership.role_in_section,
      status: membership.status,
    });
  };

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <Card style={{ display: "grid", gap: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>Classes</div>
            <div style={{ fontSize: 12, color: D.muted, marginTop: 4 }}>
              Aurora-backed sections and their memberships.
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Tag color={D.blue}>{sections.length} total</Tag>
            <Tag color={D.green}>{activeCount} active</Tag>
            <Tag color={D.orange}>{membershipCount} memberships</Tag>
          </div>
        </div>
        {loading && <div style={{ fontSize: 12, color: D.muted }}>Loading sections...</div>}
        {formError && <div style={{ fontSize: 12, color: D.red }}>{formError}</div>}
        {formStatus && <div style={{ fontSize: 12, color: D.green }}>{formStatus}</div>}
      </Card>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 14,
          alignItems: "start",
        }}
      >
        <Card style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>Create section</div>
            <Tag color={D.muted}>new</Tag>
          </div>
          <div style={{ display: "grid", gap: 10 }}>
            <label style={{ display: "grid", gap: 5 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Section ID</span>
              <input
                value={createDraft.section_id}
                onChange={(event) =>
                  setCreateDraft((current) => ({ ...current, section_id: event.target.value }))
                }
                placeholder="mit14-fall-001"
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
              <span style={{ fontSize: 12, color: D.muted }}>Course ID</span>
              <input
                value={createDraft.course_id}
                onChange={(event) =>
                  setCreateDraft((current) => ({ ...current, course_id: event.target.value }))
                }
                placeholder="mit14"
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
                placeholder="MIT 6.0014 Section A"
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
              <span style={{ fontSize: 12, color: D.muted }}>Term</span>
              <input
                value={createDraft.term}
                onChange={(event) =>
                  setCreateDraft((current) => ({ ...current, term: event.target.value }))
                }
                placeholder="Fall 2026"
                style={{
                  background: D.bg,
                  color: D.text,
                  border: `1px solid ${D.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                }}
              />
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: D.muted }}>
              <input
                type="checkbox"
                checked={createDraft.is_active}
                onChange={(event) =>
                  setCreateDraft((current) => ({ ...current, is_active: event.target.checked }))
                }
              />
              Active on create
            </label>
            <div>
              <Btn small onClick={() => void handleCreateSection()} disabled={creating || loading}>
                {creating ? "Creating..." : "Create section"}
              </Btn>
            </div>
          </div>
        </Card>

        <Card style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>
              {selectedSection ? `Manage ${selectedSection.section_id}` : "Manage section"}
            </div>
            {selectedSection ? (
              <Tag color={selectedSection.is_active ? D.green : D.yellow}>
                {selectedSection.is_active ? "active" : "inactive"}
              </Tag>
            ) : (
              <Tag color={D.muted}>select one</Tag>
            )}
          </div>
          {selectedSection ? (
            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "grid", gap: 2 }}>
                <div style={{ fontSize: 14, fontWeight: 600 }}>{selectedSection.display_name}</div>
                <div style={{ fontSize: 12, color: D.muted }}>
                  {selectedSection.course_id} · {selectedSection.course_display_name}
                </div>
                <div style={{ fontSize: 11, color: D.dim }}>Term: {selectedSection.term || "n/a"}</div>
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
                  <span style={{ fontSize: 12, color: D.muted }}>Term</span>
                  <input
                    value={editDraft.term}
                    onChange={(event) =>
                      setEditDraft((current) => ({ ...current, term: event.target.value }))
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
                <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: D.muted }}>
                  <input
                    type="checkbox"
                    checked={editDraft.is_active}
                    onChange={(event) =>
                      setEditDraft((current) => ({ ...current, is_active: event.target.checked }))
                    }
                  />
                  Active
                </label>
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <Btn
                  small
                  onClick={() => void handleSaveSection()}
                  disabled={savingSectionId === selectedSection.section_id || loading}
                >
                  {savingSectionId === selectedSection.section_id ? "Saving..." : "Save section"}
                </Btn>
                <Tag color={D.blue}>{selectedSection.memberships.length} memberships</Tag>
              </div>
            </div>
          ) : (
            <div style={{ fontSize: 12, color: D.dim }}>Select a section to edit its Aurora record.</div>
          )}
        </Card>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 14,
          alignItems: "start",
        }}
      >
        <Card style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>Assign membership</div>
            <Tag color={D.muted}>Aurora</Tag>
          </div>
          {selectedSection ? (
            <div style={{ display: "grid", gap: 10 }}>
              <label style={{ display: "grid", gap: 5 }}>
                <span style={{ fontSize: 12, color: D.muted }}>User</span>
                <select
                  value={membershipCreateDraft.user_id}
                  onChange={(event) =>
                    setMembershipCreateDraft((current) => ({
                      ...current,
                      user_id: event.target.value,
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
                  {users.length === 0 && <option value="">No users found</option>}
                  {users.map((user) => (
                    <option key={user.user_id} value={user.user_id}>
                      {user.display_name || user.email} · {user.primary_role} · {user.status}
                    </option>
                  ))}
                </select>
              </label>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <label style={{ display: "grid", gap: 5 }}>
                  <span style={{ fontSize: 12, color: D.muted }}>Section role</span>
                  <select
                    value={membershipCreateDraft.role_in_section}
                    onChange={(event) =>
                      setMembershipCreateDraft((current) => ({
                        ...current,
                        role_in_section: event.target.value as SectionMembershipRole,
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
                    value={membershipCreateDraft.status}
                    onChange={(event) =>
                      setMembershipCreateDraft((current) => ({
                        ...current,
                        status: event.target.value as SectionMembershipStatus,
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
              <div>
                <Btn small onClick={() => void handleCreateMembership()} disabled={savingMembership}>
                  {savingMembership ? "Assigning..." : "Assign user"}
                </Btn>
              </div>
            </div>
          ) : (
            <div style={{ fontSize: 12, color: D.dim }}>Select a section to assign memberships.</div>
          )}
        </Card>

        <Card style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>Edit membership</div>
            {selectedMembership ? (
              <Tag color={D.green}>{selectedMembership.role_in_section}</Tag>
            ) : (
              <Tag color={D.muted}>select one</Tag>
            )}
          </div>
          {selectedSection && selectedSection.memberships.length > 0 ? (
            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "grid", gap: 8 }}>
                {selectedSection.memberships.map((membership) => {
                  const user = users.find((candidate) => candidate.user_id === membership.user_id);
                  const isSelected = selectedMembershipUserId === membership.user_id;
                  return (
                    <Card
                      key={`${membership.section_id}-${membership.user_id}`}
                      onClick={() => selectMembership(selectedSection, membership.user_id ?? "")}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 12,
                        padding: 12,
                        borderColor: isSelected ? D.orangeBorder : D.border,
                        background: isSelected ? D.orangeGlow : D.card,
                      }}
                    >
                      <Avatar name={user?.display_name || user?.email || membership.section_id} size={30} />
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 13, fontWeight: 500 }}>
                          {user?.display_name || user?.email || membership.user_id}
                        </div>
                        <div style={{ fontSize: 11, color: D.muted }}>
                          {membership.role_in_section} · {membership.status}
                        </div>
                      </div>
                    </Card>
                  );
                })}
              </div>
              {selectedMembership ? (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <label style={{ display: "grid", gap: 5 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>Section role</span>
                    <select
                      value={membershipEditDraft.role_in_section}
                      onChange={(event) =>
                        setMembershipEditDraft((current) => ({
                          ...current,
                          role_in_section: event.target.value as SectionMembershipRole,
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
                      value={membershipEditDraft.status}
                      onChange={(event) =>
                        setMembershipEditDraft((current) => ({
                          ...current,
                          status: event.target.value as SectionMembershipStatus,
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
              ) : null}
              <div>
                <Btn small onClick={() => void handleSaveMembership()} disabled={savingMembership}>
                  {savingMembership ? "Saving..." : "Update membership"}
                </Btn>
              </div>
            </div>
          ) : (
            <div style={{ fontSize: 12, color: D.dim }}>Select a membership to edit it.</div>
          )}
        </Card>
      </div>

      <Card style={{ display: "grid", gap: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
          <div style={{ fontSize: 15, fontWeight: 600 }}>All sections</div>
          <Tag color={D.muted}>{sections.length} shown</Tag>
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          {sections.length === 0 && !loading ? (
            <div style={{ fontSize: 12, color: D.dim }}>No sections found.</div>
          ) : (
            sections.map((section) => {
              const isSelected = section.section_id === selectedSectionId;
              return (
                <Card
                  key={section.section_id}
                  onClick={() => applySelectedSection(section)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 14,
                    borderColor: isSelected ? D.orangeBorder : D.border,
                    background: isSelected ? D.orangeGlow : D.card,
                  }}
                >
                  <Avatar name={section.display_name} />
                  <div style={{ flex: 1 }}>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>{section.display_name}</div>
                    <div style={{ fontSize: 11, color: D.muted }}>
                      {section.section_id} · {section.course_id} · {section.term || "n/a"}
                    </div>
                  </div>
                  <Tag color={section.is_active ? D.green : D.yellow}>
                    {section.is_active ? "active" : "inactive"}
                  </Tag>
                  <Tag color={D.blue}>{section.memberships.length} memberships</Tag>
                </Card>
              );
            })
          )}
        </div>
      </Card>
    </div>
  );
}
