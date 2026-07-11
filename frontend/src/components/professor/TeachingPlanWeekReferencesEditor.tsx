import { useEffect, useMemo, useState } from "react";

import {
  createProfessorTeachingPlanWeekReference,
  deleteProfessorTeachingPlanWeekReference,
  type ProfessorTeachingPlanWeek,
  type ProfessorTeachingPlanWeekReference,
  type ProfessorTeachingPlanWeekReferenceCreatePayload,
  type ProfessorTeachingPlanWeekReferenceUpdatePayload,
  updateProfessorTeachingPlanWeekReference,
} from "../../api/teachingPlanApi";
import { Btn, Card, Tag } from "../../design/atoms";
import { D } from "../../design/tokens";

interface TeachingPlanWeekReferencesEditorProps {
  sectionId: string;
  week: ProfessorTeachingPlanWeek;
  accessToken: string;
  onWeekUpdated: (week: ProfessorTeachingPlanWeek) => void;
}

const referenceTypes = [
  { value: "course_doc", label: "Course doc" },
  { value: "external_link", label: "External link" },
  { value: "assignment", label: "Assignment" },
  { value: "reading", label: "Reading" },
  { value: "tooling", label: "Tooling" },
] as const;

function emptyReferenceDraft(): ProfessorTeachingPlanWeekReferenceCreatePayload {
  return {
    title: "",
    reference_type: "course_doc",
    url: "",
    course_document_key: "",
    notes: "",
    enabled: true,
    include_in_prompt: true,
    include_in_retrieval: false,
    sort_order: 0,
  };
}

function referenceFromWeek(
  reference: ProfessorTeachingPlanWeekReference,
): ProfessorTeachingPlanWeekReferenceCreatePayload {
  return {
    title: reference.title,
    reference_type: reference.reference_type,
    url: reference.url,
    course_document_key: reference.course_document_key,
    notes: reference.notes,
    enabled: reference.enabled,
    include_in_prompt: reference.include_in_prompt,
    include_in_retrieval: reference.include_in_retrieval,
    sort_order: reference.sort_order,
  };
}

export function TeachingPlanWeekReferencesEditor({
  sectionId,
  week,
  accessToken,
  onWeekUpdated,
}: TeachingPlanWeekReferencesEditorProps) {
  const [referenceDrafts, setReferenceDrafts] = useState<
    Record<string, ProfessorTeachingPlanWeekReferenceCreatePayload>
  >({});
  const [newReference, setNewReference] = useState<ProfessorTeachingPlanWeekReferenceCreatePayload>(
    emptyReferenceDraft(),
  );
  const [busyReferenceId, setBusyReferenceId] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setReferenceDrafts(
      Object.fromEntries(
        week.references.map((reference) => [reference.reference_id, referenceFromWeek(reference)]),
      ),
    );
  }, [week.references, week.week_id]);

  useEffect(() => {
    setNewReference(emptyReferenceDraft());
    setStatus(null);
    setError(null);
  }, [week.week_id]);

  const referenceCountLabel = useMemo(
    () => `${week.references.length} reference${week.references.length === 1 ? "" : "s"}`,
    [week.references.length],
  );

  const updateReferenceDraft = (
    referenceId: string,
    patch: Partial<ProfessorTeachingPlanWeekReferenceCreatePayload>,
  ) => {
    setReferenceDrafts((current) => ({
      ...current,
      [referenceId]: {
        ...(current[referenceId] ?? emptyReferenceDraft()),
        ...patch,
      },
    }));
  };

  const updateNewReferenceDraft = (
    patch: Partial<ProfessorTeachingPlanWeekReferenceCreatePayload>,
  ) => {
    setNewReference((current) => ({
      ...current,
      ...patch,
    }));
  };

  const saveReference = async (reference: ProfessorTeachingPlanWeekReference) => {
    setBusyReferenceId(reference.reference_id);
    setError(null);
    setStatus(null);
    try {
      const payload: ProfessorTeachingPlanWeekReferenceUpdatePayload = {
        ...(referenceDrafts[reference.reference_id] ?? referenceFromWeek(reference)),
      };
      const updatedWeek = await updateProfessorTeachingPlanWeekReference(
        sectionId,
        week.week_id,
        reference.reference_id,
        accessToken,
        payload,
      );
      onWeekUpdated(updatedWeek);
      setStatus(`Saved reference "${payload.title ?? reference.title}".`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save reference.");
    } finally {
      setBusyReferenceId(null);
    }
  };

  const createReference = async () => {
    setBusyReferenceId("new");
    setError(null);
    setStatus(null);
    try {
      const updatedWeek = await createProfessorTeachingPlanWeekReference(
        sectionId,
        week.week_id,
        accessToken,
        newReference,
      );
      onWeekUpdated(updatedWeek);
      setNewReference(emptyReferenceDraft());
      setStatus(`Added reference "${newReference.title}".`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to add reference.");
    } finally {
      setBusyReferenceId(null);
    }
  };

  const deleteReference = async (reference: ProfessorTeachingPlanWeekReference) => {
    setBusyReferenceId(reference.reference_id);
    setError(null);
    setStatus(null);
    try {
      const updatedWeek = await deleteProfessorTeachingPlanWeekReference(
        sectionId,
        week.week_id,
        reference.reference_id,
        accessToken,
      );
      onWeekUpdated(updatedWeek);
      setStatus(`Deleted reference "${reference.title}".`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to delete reference.");
    } finally {
      setBusyReferenceId(null);
    }
  };

  return (
    <Card style={{ display: "grid", gap: 12, background: "#fffdfa" }}>
      <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
        <div style={{ display: "grid", gap: 4 }}>
          <div style={{ fontSize: 15, fontWeight: 700 }}>Week references</div>
          <div style={{ fontSize: 12, color: D.muted, lineHeight: 1.5 }}>
            Section-approved links and documents can be surfaced in the prompt or retrieval path.
          </div>
        </div>
        <Tag color={D.orange}>{referenceCountLabel}</Tag>
      </div>

      {error && <div style={{ fontSize: 12, color: D.red }}>{error}</div>}
      {status && <div style={{ fontSize: 12, color: D.green }}>{status}</div>}

      {week.references.length === 0 ? (
        <div style={{ fontSize: 12, color: D.muted }}>
          No references are attached to this week yet.
        </div>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {week.references.map((reference) => (
            <Card key={reference.reference_id} style={{ display: "grid", gap: 10, padding: 14 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                <div style={{ display: "grid", gap: 2 }}>
                  <div style={{ fontSize: 13, fontWeight: 700 }}>
                    {reference.title || "Untitled reference"}
                  </div>
                  <div style={{ fontSize: 11, color: D.muted }}>
                    {reference.reference_type} · {reference.enabled ? "enabled" : "disabled"}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <Btn
                    small
                    variant="ghost"
                    onClick={() => void saveReference(reference)}
                    disabled={busyReferenceId === reference.reference_id}
                  >
                    {busyReferenceId === reference.reference_id ? "Saving..." : "Save reference"}
                  </Btn>
                  <Btn
                    small
                    variant="danger"
                    onClick={() => void deleteReference(reference)}
                    disabled={busyReferenceId === reference.reference_id}
                  >
                    Delete
                  </Btn>
                </div>
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                  gap: 10,
                }}
              >
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: D.muted }}>Reference title</span>
                  <input
                    value={referenceDrafts[reference.reference_id]?.title ?? reference.title}
                    onChange={(event) =>
                      updateReferenceDraft(reference.reference_id, { title: event.target.value })
                    }
                    style={{ ...referenceInputStyle }}
                  />
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: D.muted }}>Reference type</span>
                  <select
                    value={referenceDrafts[reference.reference_id]?.reference_type ?? reference.reference_type}
                    onChange={(event) =>
                      updateReferenceDraft(reference.reference_id, {
                        reference_type: event.target.value as ProfessorTeachingPlanWeekReferenceCreatePayload["reference_type"],
                      })
                    }
                    style={{ ...referenceInputStyle }}
                  >
                    {referenceTypes.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label style={{ display: "grid", gap: 6 }}>
                  <span style={{ fontSize: 12, color: D.muted }}>Reference sort order</span>
                  <input
                    type="number"
                    value={referenceDrafts[reference.reference_id]?.sort_order ?? reference.sort_order}
                    onChange={(event) =>
                      updateReferenceDraft(reference.reference_id, {
                        sort_order: Number(event.target.value) || 0,
                      })
                    }
                    style={{ ...referenceInputStyle }}
                  />
                </label>
              </div>

              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontSize: 12, color: D.muted }}>Reference course document key</span>
                <input
                  value={
                    referenceDrafts[reference.reference_id]?.course_document_key ??
                    reference.course_document_key
                  }
                  onChange={(event) =>
                    updateReferenceDraft(reference.reference_id, {
                      course_document_key: event.target.value,
                    })
                  }
                  style={{ ...referenceInputStyle }}
                />
              </label>

              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontSize: 12, color: D.muted }}>Reference URL</span>
                <input
                  value={referenceDrafts[reference.reference_id]?.url ?? reference.url}
                  onChange={(event) =>
                    updateReferenceDraft(reference.reference_id, { url: event.target.value })
                  }
                  style={{ ...referenceInputStyle }}
                />
              </label>

              <label style={{ display: "grid", gap: 6 }}>
                <span style={{ fontSize: 12, color: D.muted }}>Reference notes</span>
                <textarea
                  value={referenceDrafts[reference.reference_id]?.notes ?? reference.notes}
                  onChange={(event) =>
                    updateReferenceDraft(reference.reference_id, { notes: event.target.value })
                  }
                  rows={3}
                  style={{ ...referenceInputStyle, resize: "vertical", minHeight: 72 }}
                />
              </label>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
                  gap: 10,
                }}
              >
                <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={
                      referenceDrafts[reference.reference_id]?.enabled ?? reference.enabled
                    }
                    onChange={(event) =>
                      updateReferenceDraft(reference.reference_id, { enabled: event.target.checked })
                    }
                  />
                  <span style={{ fontSize: 12 }}>Enabled</span>
                </label>
                <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={
                      referenceDrafts[reference.reference_id]?.include_in_prompt ??
                      reference.include_in_prompt
                    }
                    onChange={(event) =>
                      updateReferenceDraft(reference.reference_id, {
                        include_in_prompt: event.target.checked,
                      })
                    }
                  />
                  <span style={{ fontSize: 12 }}>Include in prompt</span>
                </label>
                <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={
                      referenceDrafts[reference.reference_id]?.include_in_retrieval ??
                      reference.include_in_retrieval
                    }
                    onChange={(event) =>
                      updateReferenceDraft(reference.reference_id, {
                        include_in_retrieval: event.target.checked,
                      })
                    }
                  />
                  <span style={{ fontSize: 12 }}>Include in retrieval</span>
                </label>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Card style={{ display: "grid", gap: 10, background: "#fff" }}>
        <div style={{ fontSize: 13, fontWeight: 700 }}>Add reference</div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 10,
          }}
        >
          <label style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 12, color: D.muted }}>New reference title</span>
            <input
              value={newReference.title}
              onChange={(event) => updateNewReferenceDraft({ title: event.target.value })}
              style={{ ...referenceInputStyle }}
            />
          </label>
          <label style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 12, color: D.muted }}>New reference type</span>
            <select
              value={newReference.reference_type ?? "course_doc"}
              onChange={(event) =>
                updateNewReferenceDraft({
                  reference_type: event.target.value as ProfessorTeachingPlanWeekReferenceCreatePayload["reference_type"],
                })
              }
              style={{ ...referenceInputStyle }}
            >
              {referenceTypes.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 12, color: D.muted }}>New reference sort order</span>
            <input
              type="number"
              value={newReference.sort_order ?? 0}
              onChange={(event) =>
                updateNewReferenceDraft({ sort_order: Number(event.target.value) || 0 })
              }
              style={{ ...referenceInputStyle }}
            />
          </label>
        </div>

        <label style={{ display: "grid", gap: 6 }}>
          <span style={{ fontSize: 12, color: D.muted }}>New reference course document key</span>
          <input
            value={newReference.course_document_key ?? ""}
            onChange={(event) =>
              updateNewReferenceDraft({ course_document_key: event.target.value })
            }
            style={{ ...referenceInputStyle }}
          />
        </label>

        <label style={{ display: "grid", gap: 6 }}>
          <span style={{ fontSize: 12, color: D.muted }}>New reference URL</span>
          <input
            value={newReference.url ?? ""}
            onChange={(event) => updateNewReferenceDraft({ url: event.target.value })}
            style={{ ...referenceInputStyle }}
          />
        </label>

        <label style={{ display: "grid", gap: 6 }}>
          <span style={{ fontSize: 12, color: D.muted }}>New reference notes</span>
          <textarea
            value={newReference.notes ?? ""}
            onChange={(event) => updateNewReferenceDraft({ notes: event.target.value })}
            rows={3}
            style={{ ...referenceInputStyle, resize: "vertical", minHeight: 72 }}
          />
        </label>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 10,
          }}
        >
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={newReference.enabled ?? true}
              onChange={(event) => updateNewReferenceDraft({ enabled: event.target.checked })}
            />
            <span style={{ fontSize: 12 }}>Enabled</span>
          </label>
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={newReference.include_in_prompt ?? true}
              onChange={(event) =>
                updateNewReferenceDraft({ include_in_prompt: event.target.checked })
              }
            />
            <span style={{ fontSize: 12 }}>Include in prompt</span>
          </label>
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={newReference.include_in_retrieval ?? false}
              onChange={(event) =>
                updateNewReferenceDraft({ include_in_retrieval: event.target.checked })
              }
            />
            <span style={{ fontSize: 12 }}>Include in retrieval</span>
          </label>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <Btn
            small
            onClick={() => void createReference()}
            disabled={busyReferenceId === "new"}
          >
            {busyReferenceId === "new" ? "Adding..." : "Add reference"}
          </Btn>
        </div>
      </Card>
    </Card>
  );
}

const referenceInputStyle = {
  background: D.card,
  border: `1px solid ${D.border}`,
  color: D.text,
  borderRadius: 8,
  padding: "8px 10px",
  fontSize: 13,
  width: "100%",
};
