import { useEffect, useState } from "react";
import { addAdminCourseAliases, createAdminCourse, listAdminCourses, removeAdminCourseAlias, type AdminCourse, type AdminCourseSource, updateAdminCourse } from "../../api/adminCoursesApi";
import { Btn, Card, Tag } from "../../design/atoms";
import { D, mono } from "../../design/tokens";

interface CourseManagementPanelProps {
  accessToken: string;
}

interface CreateDraft {
  course_id: string;
  display_name: string;
  retrieval_profile: RetrievalProfile;
  collection_name: string;
  aliases_text: string;
  is_active: boolean;
  syllabus_matrix: string;
  style_guide: string;
}

interface EditDraft {
  display_name: string;
  retrieval_profile: RetrievalProfile;
  collection_name: string;
  is_active: boolean;
  syllabus_matrix: string;
  style_guide: string;
}

type RetrievalProfile = "mit" | "cs50";

const RETRIEVAL_PROFILE_OPTIONS: Array<{
  value: RetrievalProfile;
  label: string;
  help: string;
}> = [
  {
    value: "mit",
    label: "MIT-style",
    help: "Uses the standard syllabus + semantic + strict-rules retrieval flow.",
  },
  {
    value: "cs50",
    label: "CS50-style",
    help: "Uses the Harvard/CS50 retrieval flow for notes and transcripts.",
  },
];

const DEFAULT_PROFILE: RetrievalProfile = "mit";

function normalizeCollectionName(courseId: string): string {
  const normalized = courseId
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");

  return normalized ? `course_${normalized}` : "course_new";
}

function parseAliases(rawValue: string): string[] {
  const seen = new Set<string>();
  const aliases: string[] = [];

  for (const token of rawValue.split(/[\n,;]+/)) {
    const alias = token.trim();
    if (!alias || seen.has(alias)) {
      continue;
    }
    seen.add(alias);
    aliases.push(alias);
  }

  return aliases;
}

function profileFromCourseSource(value: AdminCourseSource): RetrievalProfile {
  return value === "cs50" ? "cs50" : "mit";
}

function courseSourceFromProfile(
  profile: RetrievalProfile,
  currentSource?: AdminCourseSource
): AdminCourseSource {
  if (profile === "cs50") {
    return "cs50";
  }
  if (currentSource === "mit13") {
    return "mit13";
  }
  return "mit14";
}

function retrievalProfileLabel(value: AdminCourseSource): string {
  const profile = profileFromCourseSource(value);
  return (
    RETRIEVAL_PROFILE_OPTIONS.find((option) => option.value === profile)?.label ?? value
  );
}

function emptyCreateDraft(): CreateDraft {
  return {
    course_id: "",
    display_name: "",
    retrieval_profile: DEFAULT_PROFILE,
    collection_name: "",
    aliases_text: "",
    is_active: true,
    syllabus_matrix: "",
    style_guide: "",
  };
}

function emptyEditDraft(): EditDraft {
  return {
    display_name: "",
    retrieval_profile: DEFAULT_PROFILE,
    collection_name: "",
    is_active: true,
    syllabus_matrix: "",
    style_guide: "",
  };
}

export function CourseManagementPanel({ accessToken }: CourseManagementPanelProps) {
  const [courses, setCourses] = useState<AdminCourse[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);
  const [formStatus, setFormStatus] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [savingCourseId, setSavingCourseId] = useState<string | null>(null);
  const [aliasSaving, setAliasSaving] = useState(false);
  const [createCollectionTouched, setCreateCollectionTouched] = useState(false);
  const [createDraft, setCreateDraft] = useState<CreateDraft>(emptyCreateDraft());
  const [editDraft, setEditDraft] = useState<EditDraft>(emptyEditDraft());
  const [aliasInput, setAliasInput] = useState("");

  const selectedCourse = courses.find((course) => course.course_id === selectedCourseId) ?? null;
  const selectedCourseCollectionChanged =
    selectedCourse !== null &&
    editDraft.collection_name.trim() !== selectedCourse.collection_name.trim();
  const selectedCourseCollectionWarning =
    Boolean(selectedCourse?.has_ingestion_history) && selectedCourseCollectionChanged;

  const applySelectedCourse = (course: AdminCourse | null) => {
    setSelectedCourseId(course?.course_id ?? null);
    if (course === null) {
      setEditDraft(emptyEditDraft());
      setAliasInput("");
      return;
    }

    setEditDraft({
      display_name: course.display_name,
      retrieval_profile: profileFromCourseSource(course.course_source),
      collection_name: course.collection_name,
      is_active: course.is_active,
      syllabus_matrix: course.syllabus_matrix ?? "",
      style_guide: course.style_guide ?? "",
    });
    setAliasInput("");
  };

  const upsertCourse = (nextCourse: AdminCourse) => {
    setCourses((current) => {
      const next = current.filter((course) => course.course_id !== nextCourse.course_id);
      next.push(nextCourse);
      next.sort((left, right) => left.course_id.localeCompare(right.course_id));
      return next;
    });
  };

  useEffect(() => {
    let cancelled = false;

    void listAdminCourses(accessToken)
      .then((nextCourses) => {
        if (cancelled) {
          return;
        }
        setCourses(nextCourses);
        applySelectedCourse(nextCourses[0] ?? null);
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setCourses([]);
          applySelectedCourse(null);
          setFormError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  const activeCount = courses.filter((course) => course.is_active).length;
  const aliasCount = courses.reduce((total, course) => total + course.aliases.length, 0);

  const handleCreateCourse = async () => {
    const courseId = createDraft.course_id.trim();
    const displayName = createDraft.display_name.trim();
    const collectionName = createDraft.collection_name.trim();
    const aliases = parseAliases(createDraft.aliases_text);

    setCreating(true);
    setFormError(null);
    setFormStatus(null);

    try {
      if (!courseId) {
        throw new Error("Course ID is required.");
      }
      if (!displayName) {
        throw new Error("Display name is required.");
      }
      if (!collectionName) {
        throw new Error("Collection name is required.");
      }

      const created = await createAdminCourse(accessToken, {
        course_id: courseId,
        display_name: displayName,
        course_source: courseSourceFromProfile(createDraft.retrieval_profile),
        collection_name: collectionName,
        is_active: createDraft.is_active,
        aliases,
        syllabus_matrix: createDraft.syllabus_matrix.trim() || undefined,
        style_guide: createDraft.style_guide.trim() || undefined,
      });
      upsertCourse(created);
      applySelectedCourse(created);
      setCreateDraft(emptyCreateDraft());
      setCreateCollectionTouched(false);
      setFormStatus(`Created ${created.course_id}.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to create course.");
    } finally {
      setCreating(false);
    }
  };

  const handleSaveCourse = async () => {
    if (selectedCourse === null) {
      return;
    }

    const displayName = editDraft.display_name.trim();
    const collectionName = editDraft.collection_name.trim();

    setSavingCourseId(selectedCourse.course_id);
    setFormError(null);
    setFormStatus(null);

    try {
      if (!displayName) {
        throw new Error("Display name is required.");
      }
      if (!collectionName) {
        throw new Error("Collection name is required.");
      }
      if (selectedCourse.has_ingestion_history && collectionName !== selectedCourse.collection_name) {
        const confirmed = window.confirm(
          "This course already has ingestion history. Changing the collection name can point retrieval at a different Qdrant collection. Continue?"
        );
        if (!confirmed) {
          setSavingCourseId(null);
          return;
        }
      }

      const updated = await updateAdminCourse(selectedCourse.course_id, accessToken, {
        display_name: displayName,
        course_source: courseSourceFromProfile(
          editDraft.retrieval_profile,
          selectedCourse.course_source
        ),
        collection_name: collectionName,
        is_active: editDraft.is_active,
        syllabus_matrix: editDraft.syllabus_matrix.trim() || undefined,
        style_guide: editDraft.style_guide.trim() || undefined,
      });
      upsertCourse(updated);
      applySelectedCourse(updated);
      setFormStatus(`Updated ${updated.course_id}.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to update course.");
    } finally {
      setSavingCourseId(null);
    }
  };

  const handleAddAliases = async () => {
    if (selectedCourse === null) {
      return;
    }

    const aliases = parseAliases(aliasInput);

    setAliasSaving(true);
    setFormError(null);
    setFormStatus(null);

    try {
      if (aliases.length === 0) {
        throw new Error("Enter at least one alias.");
      }

      const updated = await addAdminCourseAliases(selectedCourse.course_id, accessToken, {
        aliases,
      });
      upsertCourse(updated);
      applySelectedCourse(updated);
      setAliasInput("");
      setFormStatus(`Added ${aliases.length} alias${aliases.length === 1 ? "" : "es"}.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to add aliases.");
    } finally {
      setAliasSaving(false);
    }
  };

  const handleRemoveAlias = async (alias: string) => {
    if (selectedCourse === null) {
      return;
    }

    setAliasSaving(true);
    setFormError(null);
    setFormStatus(null);

    try {
      const updated = await removeAdminCourseAlias(selectedCourse.course_id, alias, accessToken);
      upsertCourse(updated);
      applySelectedCourse(updated);
      setFormStatus(`Removed alias ${alias}.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to remove alias.");
    } finally {
      setAliasSaving(false);
    }
  };

  const courseStatusLabel = (course: AdminCourse) =>
    course.is_active ? (
      <Tag color={D.green}>active</Tag>
    ) : (
      <Tag color={D.yellow}>inactive</Tag>
    );

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <Card style={{ display: "grid", gap: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>Courses</div>
            <div style={{ fontSize: 12, color: D.muted, marginTop: 4 }}>
              Aurora-backed course registry used by ingestion and retrieval.
            </div>
          </div>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
            <Tag color={D.blue}>{courses.length} total</Tag>
            <Tag color={D.green}>{activeCount} active</Tag>
            <Tag color={D.orange}>{aliasCount} aliases</Tag>
          </div>
        </div>
        {loading && <div style={{ fontSize: 12, color: D.muted }}>Loading courses...</div>}
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
            <div style={{ fontSize: 15, fontWeight: 600 }}>Create course</div>
            <Tag color={D.muted}>new</Tag>
          </div>
          <div style={{ display: "grid", gap: 10 }}>
            <label style={{ display: "grid", gap: 5 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Course ID</span>
              <input
                value={createDraft.course_id}
                onChange={(e) => {
                  const nextValue = e.target.value;
                  setCreateDraft((current) => ({
                    ...current,
                    course_id: nextValue,
                    collection_name: createCollectionTouched
                      ? current.collection_name
                      : normalizeCollectionName(nextValue),
                  }));
                }}
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
                onChange={(e) =>
                  setCreateDraft((current) => ({ ...current, display_name: e.target.value }))
                }
                placeholder="MIT 6.0014 Introduction to Python"
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
                <span style={{ fontSize: 12, color: D.muted }}>Retrieval profile</span>
              <select
                value={createDraft.retrieval_profile}
                onChange={(e) =>
                  setCreateDraft((current) => ({
                    ...current,
                    retrieval_profile: e.target.value as RetrievalProfile,
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
                {RETRIEVAL_PROFILE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <div style={{ fontSize: 11, color: D.muted }}>
                {
                  RETRIEVAL_PROFILE_OPTIONS.find(
                    (option) => option.value === createDraft.retrieval_profile
                  )?.help
                }
              </div>
            </label>
            <label style={{ display: "grid", gap: 5 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Collection name</span>
              <input
                value={createDraft.collection_name}
                onChange={(e) => {
                  setCreateCollectionTouched(true);
                  setCreateDraft((current) => ({ ...current, collection_name: e.target.value }));
                }}
                placeholder={normalizeCollectionName(createDraft.course_id)}
                style={{
                  background: D.bg,
                  color: D.text,
                  border: `1px solid ${D.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                }}
              />
              <div style={{ fontSize: 11, color: D.muted }}>
                Used by Qdrant. The default suggestion is based on the course ID.
              </div>
            </label>
            <label style={{ display: "grid", gap: 5 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Aliases</span>
              <input
                value={createDraft.aliases_text}
                onChange={(e) =>
                  setCreateDraft((current) => ({ ...current, aliases_text: e.target.value }))
                }
                placeholder="cs-202, intro-cpp"
                style={{
                  background: D.bg,
                  color: D.text,
                  border: `1px solid ${D.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                }}
              />
              <div style={{ fontSize: 11, color: D.muted }}>
                Separate aliases with commas, semicolons, or new lines.
              </div>
            </label>
            <label style={{ display: "grid", gap: 5 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Syllabus matrix (JSON array/object)</span>
              <textarea
                value={createDraft.syllabus_matrix}
                onChange={(e) =>
                  setCreateDraft((current) => ({ ...current, syllabus_matrix: e.target.value }))
                }
                rows={4}
                style={{
                  background: D.bg,
                  color: D.text,
                  border: `1px solid ${D.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                  ...mono,
                  fontSize: 12,
                }}
                placeholder='{"1": {"allowed": "...", "forbidden": "..."}}'
              />
            </label>
            <label style={{ display: "grid", gap: 5 }}>
              <span style={{ fontSize: 12, color: D.muted }}>Style guide (Markdown/Text)</span>
              <textarea
                value={createDraft.style_guide}
                onChange={(e) =>
                  setCreateDraft((current) => ({ ...current, style_guide: e.target.value }))
                }
                rows={4}
                style={{
                  background: D.bg,
                  color: D.text,
                  border: `1px solid ${D.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                  ...mono,
                  fontSize: 12,
                }}
                placeholder="- Indentation: 4 spaces&#10;- Braces: K&R style"
              />
            </label>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: D.muted }}>
              <input
                type="checkbox"
                checked={createDraft.is_active}
                onChange={(e) =>
                  setCreateDraft((current) => ({ ...current, is_active: e.target.checked }))
                }
              />
              Active on create
            </label>
            <div>
              <Btn
                small
                onClick={() => void handleCreateCourse()}
                disabled={creating || loading}
              >
                {creating ? "Creating..." : "Create course"}
              </Btn>
            </div>
          </div>
        </Card>

        <Card style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>
              {selectedCourse ? `Manage ${selectedCourse.course_id}` : "Manage course"}
            </div>
            {selectedCourse ? courseStatusLabel(selectedCourse) : <Tag color={D.muted}>select one</Tag>}
          </div>

          {!selectedCourse ? (
            <div style={{ fontSize: 12, color: D.muted }}>
              Select a course from the list below to edit metadata or manage aliases.
            </div>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "grid", gap: 5 }}>
                <span style={{ fontSize: 12, color: D.muted }}>Course ID</span>
                <div
                  style={{
                    background: D.surface,
                    border: `1px solid ${D.border}`,
                    borderRadius: 8,
                    padding: "10px 12px",
                    ...mono,
                    fontSize: 13,
                    color: D.dim,
                  }}
                >
                  {selectedCourse.course_id}
                </div>
              </div>
              <label style={{ display: "grid", gap: 5 }}>
                <span style={{ fontSize: 12, color: D.muted }}>Display name</span>
                <input
                  value={editDraft.display_name}
                  onChange={(e) =>
                    setEditDraft((current) => ({ ...current, display_name: e.target.value }))
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
                <span style={{ fontSize: 12, color: D.muted }}>Retrieval profile</span>
                <select
                  value={editDraft.retrieval_profile}
                  onChange={(e) =>
                    setEditDraft((current) => ({
                      ...current,
                      retrieval_profile: e.target.value as RetrievalProfile,
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
                  {RETRIEVAL_PROFILE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <div style={{ fontSize: 11, color: D.muted }}>
                  {
                    RETRIEVAL_PROFILE_OPTIONS.find(
                      (option) => option.value === editDraft.retrieval_profile
                    )?.help
                  }
                </div>
              </label>
              <label style={{ display: "grid", gap: 5 }}>
                <span style={{ fontSize: 12, color: D.muted }}>Collection name</span>
                <input
                  value={editDraft.collection_name}
                  onChange={(e) =>
                    setEditDraft((current) => ({ ...current, collection_name: e.target.value }))
                  }
                  style={{
                    background: D.bg,
                    color: D.text,
                    border: `1px solid ${D.border}`,
                    borderRadius: 8,
                    padding: "10px 12px",
                  }}
                />
                {selectedCourse && (
                  <div
                    style={{
                      fontSize: 11,
                      color: selectedCourseCollectionWarning ? D.yellow : D.muted,
                      lineHeight: 1.4,
                    }}
                  >
                    {selectedCourse.has_ingestion_history
                      ? selectedCourseCollectionWarning
                        ? "Warning: this course already has ingestion history. Changing the collection name will point retrieval at a different Qdrant collection."
                        : "This course already has ingestion history. Changing the collection name will affect where retrieval points."
                      : "Used by Qdrant. Changing it is safe for a brand-new course before any ingestion runs."}
                  </div>
                )}
              </label>
              <label style={{ display: "grid", gap: 5 }}>
                <span style={{ fontSize: 12, color: D.muted }}>Syllabus matrix (JSON array/object)</span>
                <textarea
                  value={editDraft.syllabus_matrix}
                  onChange={(e) =>
                    setEditDraft((current) => ({ ...current, syllabus_matrix: e.target.value }))
                  }
                  rows={4}
                  style={{
                    background: D.bg,
                    color: D.text,
                    border: `1px solid ${D.border}`,
                    borderRadius: 8,
                    padding: "10px 12px",
                    ...mono,
                    fontSize: 12,
                  }}
                  placeholder='{"1": {"allowed": "...", "forbidden": "..."}}'
                />
              </label>
              <label style={{ display: "grid", gap: 5 }}>
                <span style={{ fontSize: 12, color: D.muted }}>Style guide (Markdown/Text)</span>
                <textarea
                  value={editDraft.style_guide}
                  onChange={(e) =>
                    setEditDraft((current) => ({ ...current, style_guide: e.target.value }))
                  }
                  rows={4}
                  style={{
                    background: D.bg,
                    color: D.text,
                    border: `1px solid ${D.border}`,
                    borderRadius: 8,
                    padding: "10px 12px",
                    ...mono,
                    fontSize: 12,
                  }}
                  placeholder="- Indentation: 4 spaces&#10;- Braces: K&R style"
                />
              </label>
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: D.muted }}>
                <input
                  type="checkbox"
                  checked={editDraft.is_active}
                  onChange={(e) =>
                    setEditDraft((current) => ({ ...current, is_active: e.target.checked }))
                  }
                />
                Active
              </label>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <Btn
                  small
                onClick={() => void handleSaveCourse()}
                disabled={savingCourseId === selectedCourse.course_id || loading}
              >
                  {savingCourseId === selectedCourse.course_id ? "Saving..." : "Save changes"}
                </Btn>
                <Btn
                  small
                  variant="ghost"
                  onClick={() => setEditDraft(emptyEditDraft())}
                >
                  Reset
                </Btn>
              </div>

              <div style={{ borderTop: `1px solid ${D.border}`, paddingTop: 10, display: "grid", gap: 10 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>Aliases</div>
                {selectedCourse.aliases.length === 0 ? (
                  <div style={{ fontSize: 12, color: D.muted }}>No aliases attached yet.</div>
                ) : (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                    {selectedCourse.aliases.map((alias) => (
                      <div
                        key={alias}
                        style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}
                      >
                        <Tag color={D.blue}>{alias}</Tag>
                        <Btn
                          small
                          variant="ghost"
                          disabled={aliasSaving}
                  onClick={() => void handleRemoveAlias(alias)}
                        >
                          Remove
                        </Btn>
                      </div>
                    ))}
                  </div>
                )}
                <div style={{ display: "grid", gap: 8 }}>
                  <label style={{ display: "grid", gap: 5 }}>
                    <span style={{ fontSize: 12, color: D.muted }}>Add aliases</span>
                    <input
                      value={aliasInput}
                      onChange={(e) => setAliasInput(e.target.value)}
                      placeholder="cs-202, cplusplus-best-practices"
                      style={{
                        background: D.bg,
                        color: D.text,
                        border: `1px solid ${D.border}`,
                        borderRadius: 8,
                        padding: "10px 12px",
                      }}
                    />
                  </label>
                  <div>
                    <Btn
                      small
                  onClick={() => void handleAddAliases()}
                      disabled={aliasSaving || loading}
                    >
                      {aliasSaving ? "Updating aliases..." : "Add aliases"}
                    </Btn>
                  </div>
                </div>

                <div style={{ display: "grid", gap: 4, fontSize: 11, color: D.muted }}>
                  <div>Retrieval profile: {retrievalProfileLabel(selectedCourse.course_source)}</div>
                  <div>Stored route key: {selectedCourse.course_source}</div>
                  <div>Collection: {selectedCourse.collection_name}</div>
                  <div>Created: {selectedCourse.created_at || "—"}</div>
                  <div>Updated: {selectedCourse.updated_at || "—"}</div>
                </div>
              </div>
            </div>
          )}
        </Card>
      </div>

      <div style={{ display: "grid", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>All courses</div>
          <Tag color={D.muted}>click a row to manage</Tag>
        </div>
        <div style={{ display: "grid", gap: 10 }}>
          {courses.length === 0 && !loading ? (
            <Card style={{ fontSize: 12, color: D.muted }}>No courses found.</Card>
          ) : (
            courses.map((course) => {
              const isSelected = course.course_id === selectedCourseId;
              return (
                <Card
                  key={course.course_id}
                  onClick={() => applySelectedCourse(course)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    justifyContent: "space-between",
                    borderColor: isSelected ? D.orangeBorder : D.border,
                    background: isSelected ? `${D.orangeGlow}55` : D.card,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                    <div
                      style={{
                        background: D.orangeGlow,
                        border: `1px solid ${D.orangeBorder}`,
                        borderRadius: 6,
                        padding: "5px 11px",
                        ...mono,
                        fontSize: 13,
                        fontWeight: 600,
                        color: D.orange,
                        flexShrink: 0,
                      }}
                    >
                      {course.course_id}
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 14, fontWeight: 500 }}>{course.display_name}</div>
                      <div style={{ fontSize: 12, color: D.muted, marginTop: 2 }}>
                        {retrievalProfileLabel(course.course_source)} · {course.collection_name} · {course.aliases.length} alias
                        {course.aliases.length === 1 ? "" : "es"}
                      </div>
                    </div>
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
                    {courseStatusLabel(course)}
                    <Btn
                      variant="ghost"
                      small
                      onClick={() => applySelectedCourse(course)}
                    >
                      Manage
                    </Btn>
                  </div>
                </Card>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
