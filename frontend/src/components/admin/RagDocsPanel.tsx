import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";

import { listAdminCourses, type AdminCourse } from "../../api/adminCoursesApi";
import {
  createAdminCourseDocumentUploadUrl,
  deleteAdminCourseDocument,
  launchAdminIngestionJob,
  listAdminCourseCorpusVersions,
  listAdminCourseDocuments,
  listAdminIngestionJobs,
  uploadAdminCourseDocument,
  type AdminCourseCorpusVersion,
  type AdminCourseDocumentListResponse,
  type AdminIngestionJobKind,
  type AdminIngestionJobResponse,
  type AdminIngestionJobStatus,
} from "../../api/adminIngestionApi";
import { Btn, Card, Tag } from "../../design/atoms";
import { D, mono } from "../../design/tokens";

interface RagDocsPanelProps {
  accessToken: string;
}

interface CourseRagData {
  documents: AdminCourseDocumentListResponse;
  jobs: AdminIngestionJobResponse[];
  versions: AdminCourseCorpusVersion[];
}

const RUNNING_JOB_STATUSES = new Set<AdminIngestionJobStatus>(["queued", "running"]);

function formatBytes(sizeBytes: number): string {
  if (sizeBytes < 1024) {
    return `${sizeBytes} B`;
  }
  const kib = sizeBytes / 1024;
  if (kib < 1024) {
    return `${kib.toFixed(1)} KB`;
  }
  const mib = kib / 1024;
  if (mib < 1024) {
    return `${mib.toFixed(1)} MB`;
  }
  return `${(mib / 1024).toFixed(1)} GB`;
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function jobStatusColor(status: AdminIngestionJobStatus): string {
  switch (status) {
    case "completed":
      return D.green;
    case "failed":
    case "launch_failed":
      return D.red;
    case "queued":
    case "running":
      return D.yellow;
  }
}

function corpusVersionStatusColor(status: string, active: boolean): string {
  if (active) {
    return D.green;
  }
  if (status === "failed") {
    return D.red;
  }
  if (status === "queued" || status === "running") {
    return D.yellow;
  }
  return D.blue;
}

function toLaunchLabel(jobKind: AdminIngestionJobKind): string {
  return jobKind === "parse" ? "Parse" : "Chunk + Index";
}

const parseActionStyle = {
  background: `${D.blue}16`,
  color: D.blue,
  border: `1px solid ${D.blue}44`,
};

const indexActionStyle = {
  background: `${D.green}16`,
  color: D.green,
  border: `1px solid ${D.green}44`,
};

const refreshActionStyle = {
  background: `${D.text}08`,
  color: D.text,
  border: `1px solid ${D.border}`,
};

async function fetchCourseRagData(
  accessToken: string,
  courseId: string
): Promise<CourseRagData> {
  const [documents, jobs, versions] = await Promise.all([
    listAdminCourseDocuments(courseId, accessToken),
    listAdminIngestionJobs(accessToken, { courseId, limit: 10 }),
    listAdminCourseCorpusVersions(courseId, accessToken, 10),
  ]);
  return { documents, jobs, versions };
}

export function RagDocsPanel({ accessToken }: RagDocsPanelProps) {
  const [courses, setCourses] = useState<AdminCourse[]>([]);
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null);
  const [documentsState, setDocumentsState] =
    useState<AdminCourseDocumentListResponse | null>(null);
  const [jobs, setJobs] = useState<AdminIngestionJobResponse[]>([]);
  const [versions, setVersions] = useState<AdminCourseCorpusVersion[]>([]);
  const [loadingCourses, setLoadingCourses] = useState(true);
  const [loadingData, setLoadingData] = useState(false);
  const [uploadingCount, setUploadingCount] = useState(0);
  const [deletingKey, setDeletingKey] = useState<string | null>(null);
  const [launchingKind, setLaunchingKind] = useState<AdminIngestionJobKind | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [formStatus, setFormStatus] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const selectedCourse =
    courses.find((course) => course.course_id === selectedCourseId) ?? null;

  const runningJobs = useMemo(
    () => jobs.filter((job) => RUNNING_JOB_STATUSES.has(job.status)),
    [jobs]
  );
  const uploading = uploadingCount > 0;

  const activeCorpusVersion = useMemo(
    () => versions.find((version) => version.active) ?? null,
    [versions]
  );

  const refreshSelectedCourse = async (
    courseId: string,
    options?: { silent?: boolean }
  ): Promise<void> => {
    const silent = options?.silent ?? false;
    if (!silent) {
      setLoadingData(true);
    }
    try {
      const data = await fetchCourseRagData(accessToken, courseId);
      setDocumentsState(data.documents);
      setJobs(data.jobs);
      setVersions(data.versions);
    } catch (err) {
      setDocumentsState(null);
      setJobs([]);
      setVersions([]);
      setFormError(err instanceof Error ? err.message : "Unable to load course documents.");
    } finally {
      if (!silent) {
        setLoadingData(false);
      }
    }
  };

  useEffect(() => {
    let cancelled = false;

    void listAdminCourses(accessToken)
      .then((nextCourses) => {
        if (cancelled) {
          return;
        }
        setCourses(nextCourses);
        if (nextCourses.length === 0) {
          setDocumentsState(null);
          setJobs([]);
          setVersions([]);
        }
        if (nextCourses.length > 0) {
          setLoadingData(true);
        }
        setSelectedCourseId((currentSelectedCourseId) => {
          if (
            currentSelectedCourseId &&
            nextCourses.some((course) => course.course_id === currentSelectedCourseId)
          ) {
            return currentSelectedCourseId;
          }
          return nextCourses[0]?.course_id ?? null;
        });
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setCourses([]);
          setSelectedCourseId(null);
          setDocumentsState(null);
          setJobs([]);
          setVersions([]);
          setFormError(err.message);
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingCourses(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  useEffect(() => {
    if (!selectedCourseId) {
      return;
    }

    let active = true;

    void fetchCourseRagData(accessToken, selectedCourseId)
      .then((data) => {
        if (!active) {
          return;
        }
        setDocumentsState(data.documents);
        setJobs(data.jobs);
        setVersions(data.versions);
      })
      .catch((err: Error) => {
        if (!active) {
          return;
        }
        setDocumentsState(null);
        setJobs([]);
        setVersions([]);
        setFormError(err.message);
      })
      .finally(() => {
        if (active) {
          setLoadingData(false);
        }
      });

    return () => {
      active = false;
    };
  }, [accessToken, selectedCourseId]);

  useEffect(() => {
    if (!selectedCourseId || runningJobs.length === 0) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void fetchCourseRagData(accessToken, selectedCourseId)
        .then((data) => {
          setDocumentsState(data.documents);
          setJobs(data.jobs);
          setVersions(data.versions);
        })
        .catch((err: Error) => {
          setFormError(err.message);
        });
    }, 5000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [accessToken, runningJobs.length, selectedCourseId]);

  const handleOpenFilePicker = () => {
    fileInputRef.current?.click();
  };

  const handleUploadChange = async (
    event: ChangeEvent<HTMLInputElement>
  ): Promise<void> => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";

    if (files.length === 0 || !selectedCourse) {
      return;
    }

    setUploadingCount(files.length);
    setFormError(null);
    setFormStatus(null);

    let uploadedCount = 0;
    const failures: string[] = [];

    try {
      for (const [index, file] of files.entries()) {
        setFormStatus(`Uploading ${index + 1} of ${files.length}: ${file.name}...`);
        try {
          const uploadTarget = await createAdminCourseDocumentUploadUrl(
            selectedCourse.course_id,
            accessToken,
            {
              file_name: file.name,
              content_type: file.type || null,
            }
          );
          await uploadAdminCourseDocument(uploadTarget, file);
          uploadedCount += 1;
        } catch (err) {
          const message =
            err instanceof Error ? err.message : "Unable to upload document.";
          failures.push(`${file.name}: ${message}`);
        }
      }

      if (uploadedCount > 0) {
        await refreshSelectedCourse(selectedCourse.course_id);
      }

      if (uploadedCount > 0) {
        const noun = uploadedCount === 1 ? "file" : "files";
        setFormStatus(`Uploaded ${uploadedCount} ${noun}.`);
      }
      if (failures.length > 0) {
        const summary = failures.slice(0, 3).join(" ");
        const remaining = failures.length - 3;
        setFormError(
          remaining > 0 ? `${summary} ${remaining} more upload(s) failed.` : summary
        );
      }
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to upload document.");
    } finally {
      setUploadingCount(0);
    }
  };

  const handleDeleteDocument = async (
    documentKey: string,
    fileName: string
  ): Promise<void> => {
    if (!selectedCourse) {
      return;
    }
    const confirmed = window.confirm(`Delete ${fileName}?`);
    if (!confirmed) {
      return;
    }

    setDeletingKey(documentKey);
    setFormError(null);
    setFormStatus(null);

    try {
      await deleteAdminCourseDocument(selectedCourse.course_id, accessToken, documentKey);
      await refreshSelectedCourse(selectedCourse.course_id);
      setFormStatus(`Deleted ${fileName}.`);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to delete document.");
    } finally {
      setDeletingKey(null);
    }
  };

  const handleLaunchJob = async (jobKind: AdminIngestionJobKind): Promise<void> => {
    if (!selectedCourse || !documentsState) {
      return;
    }

    setLaunchingKind(jobKind);
    setFormError(null);
    setFormStatus(null);

    try {
      const response = await launchAdminIngestionJob(accessToken, {
        course_id: selectedCourse.course_id,
        job_kind: jobKind,
        bucket: documentsState.bucket,
        input_prefix:
          jobKind === "parse"
            ? documentsState.upload_prefix
            : documentsState.parsed_prefix,
        output_prefix:
          jobKind === "parse" ? documentsState.parsed_prefix : undefined,
        prepared_output_prefix:
          jobKind === "chunk-index" ? documentsState.prepared_prefix : undefined,
      });
      await refreshSelectedCourse(selectedCourse.course_id);
      setFormStatus(
        `${toLaunchLabel(jobKind)} launched as ${response.job_id}.`
      );
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Unable to launch ingestion job.");
    } finally {
      setLaunchingKind(null);
    }
  };

  const handleRefresh = async (): Promise<void> => {
    if (!selectedCourseId) {
      return;
    }
    setFormError(null);
    setFormStatus(null);
    await refreshSelectedCourse(selectedCourseId);
  };

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <Card style={{ display: "grid", gap: 10 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <div>
            <div style={{ fontSize: 18, fontWeight: 600 }}>
              RAG document library
            </div>
            <div style={{ fontSize: 12, color: D.muted, marginTop: 4 }}>
              Course-scoped source documents, ingestion jobs, and corpus versions.
            </div>
          </div>
          <div
            style={{
              display: "flex",
              gap: 8,
              flexWrap: "wrap",
              alignItems: "center",
            }}
          >
            <Tag color={D.blue}>{courses.length} courses</Tag>
            <Tag color={D.green}>{documentsState?.documents.length ?? 0} docs</Tag>
            <Tag color={D.yellow}>{runningJobs.length} running</Tag>
            <Tag color={activeCorpusVersion ? D.green : D.muted}>
              {activeCorpusVersion ? "active corpus" : "no active corpus"}
            </Tag>
          </div>
        </div>
        {loadingCourses && (
          <div style={{ fontSize: 12, color: D.muted }}>Loading courses...</div>
        )}
        {formError && <div style={{ fontSize: 12, color: D.red }}>{formError}</div>}
        {formStatus && (
          <div style={{ fontSize: 12, color: D.green }}>{formStatus}</div>
        )}
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
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 10,
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 600 }}>Course scope</div>
            <Tag color={selectedCourse?.is_active ? D.green : D.muted}>
              {selectedCourse?.is_active ? "active" : "select a course"}
            </Tag>
          </div>
          <label style={{ display: "grid", gap: 5 }}>
            <span style={{ fontSize: 12, color: D.muted }}>Course</span>
            <select
              value={selectedCourseId ?? ""}
              onChange={(event) => {
                setFormError(null);
                setFormStatus(null);
                setLoadingData(true);
                setSelectedCourseId(event.target.value || null);
              }}
              disabled={loadingCourses || courses.length === 0}
              style={{
                background: D.bg,
                color: D.text,
                border: `1px solid ${D.border}`,
                borderRadius: 8,
                padding: "10px 12px",
              }}
            >
              {courses.length === 0 && <option value="">No courses found</option>}
              {courses.map((course) => (
                <option key={course.course_id} value={course.course_id}>
                  {course.course_id} · {course.display_name}
                </option>
              ))}
            </select>
          </label>

          {selectedCourse && (
            <div style={{ display: "grid", gap: 6, fontSize: 12 }}>
              <div style={{ color: D.muted }}>
                Collection: <span style={{ color: D.text }}>{selectedCourse.collection_name}</span>
              </div>
              <div style={{ color: D.muted }}>
                Retrieval profile:{" "}
                <span style={{ color: D.text }}>{selectedCourse.course_source}</span>
              </div>
            </div>
          )}

          <div
            style={{
              display: "grid",
              gap: 8,
              borderTop: `1px solid ${D.border}`,
              paddingTop: 10,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 600 }}>Upload and ingest</div>
            <input
              ref={fileInputRef}
              type="file"
              multiple
              onChange={(event) => {
                void handleUploadChange(event);
              }}
              style={{ display: "none" }}
            />
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <Btn
                small
                onClick={handleOpenFilePicker}
                disabled={!selectedCourse || uploading || deletingKey !== null}
              >
                {uploading
                  ? `Uploading ${uploadingCount} file${uploadingCount === 1 ? "" : "s"}...`
                  : "Upload document(s)"}
              </Btn>
              <Btn
                small
                variant="ghost"
                style={parseActionStyle}
                onClick={() => {
                  void handleLaunchJob("parse");
                }}
                disabled={
                  !selectedCourse ||
                  !documentsState ||
                  launchingKind !== null ||
                  uploading ||
                  deletingKey !== null
                }
              >
                {launchingKind === "parse" ? "Launching parse..." : "Launch parse"}
              </Btn>
              <Btn
                small
                variant="ghost"
                style={indexActionStyle}
                onClick={() => {
                  void handleLaunchJob("chunk-index");
                }}
                disabled={
                  !selectedCourse ||
                  !documentsState ||
                  launchingKind !== null ||
                  uploading ||
                  deletingKey !== null
                }
              >
                {launchingKind === "chunk-index"
                  ? "Launching index..."
                  : "Launch chunk + index"}
              </Btn>
              <Btn
                small
                variant="ghost"
                style={refreshActionStyle}
                onClick={() => {
                  void handleRefresh();
                }}
                disabled={!selectedCourse || loadingData || uploading}
              >
                {loadingData ? "Refreshing..." : "Refresh"}
              </Btn>
            </div>
            {documentsState && (
              <div style={{ display: "grid", gap: 4, fontSize: 11, color: D.muted }}>
                <div>
                  Bucket: <span style={{ color: D.text }}>{documentsState.bucket}</span>
                </div>
                <div>
                  Upload prefix:{" "}
                  <span style={{ ...mono, color: D.dim }}>
                    {documentsState.upload_prefix}
                  </span>
                </div>
                <div>
                  Parsed prefix:{" "}
                  <span style={{ ...mono, color: D.dim }}>
                    {documentsState.parsed_prefix}
                  </span>
                </div>
                <div>
                  Prepared prefix:{" "}
                  <span style={{ ...mono, color: D.dim }}>
                    {documentsState.prepared_prefix}
                  </span>
                </div>
              </div>
            )}
          </div>
        </Card>

        <Card style={{ display: "grid", gap: 12 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 10,
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 600 }}>Recent jobs</div>
            <Tag color={runningJobs.length > 0 ? D.yellow : D.muted}>
              {runningJobs.length > 0 ? "polling every 5s" : "idle"}
            </Tag>
          </div>
          {jobs.length === 0 ? (
            <div style={{ fontSize: 12, color: D.muted }}>
              No ingestion jobs recorded for this course yet.
            </div>
          ) : (
            <div style={{ display: "grid", gap: 8 }}>
              {jobs.map((job) => (
                <Card
                  key={job.job_id}
                  style={{
                    padding: "12px 14px",
                    display: "grid",
                    gap: 6,
                    background: D.surface,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 10,
                      flexWrap: "wrap",
                    }}
                  >
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <Tag color={jobStatusColor(job.status)}>{job.status}</Tag>
                      <span style={{ fontSize: 13, fontWeight: 500 }}>
                        {toLaunchLabel(job.job_kind)}
                      </span>
                    </div>
                    <div style={{ ...mono, fontSize: 11, color: D.dim }}>{job.job_id}</div>
                  </div>
                  <div style={{ fontSize: 12, color: D.muted }}>{job.message || "—"}</div>
                  <div style={{ fontSize: 11, color: D.muted }}>
                    Created {formatTimestamp(job.created_at)} · Updated {formatTimestamp(job.updated_at)}
                  </div>
                </Card>
              ))}
            </div>
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
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 10,
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 600 }}>Uploaded documents</div>
            <Tag color={D.blue}>{documentsState?.documents.length ?? 0} files</Tag>
          </div>
          {!selectedCourse ? (
            <div style={{ fontSize: 12, color: D.muted }}>
              Select a course to view uploaded documents.
            </div>
          ) : documentsState?.documents.length ? (
            <div style={{ display: "grid", gap: 8 }}>
              {documentsState.documents.map((document) => (
                <Card
                  key={document.key}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "11px 14px",
                    background: D.surface,
                  }}
                >
                  <span style={{ fontSize: 16, flexShrink: 0 }}>📄</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 500 }}>
                      {document.file_name}
                    </div>
                    <div style={{ fontSize: 11, color: D.muted, marginTop: 2 }}>
                      {formatBytes(document.size_bytes)} · {formatTimestamp(document.last_modified)}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <Tag color={D.blue}>uploaded</Tag>
                    <Btn
                      small
                      variant="danger"
                      disabled={deletingKey !== null || uploading || launchingKind !== null}
                      onClick={() => {
                        void handleDeleteDocument(document.key, document.file_name);
                      }}
                    >
                      {deletingKey === document.key ? "Deleting..." : "Delete"}
                    </Btn>
                  </div>
                </Card>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 12, color: D.muted }}>
              No uploaded source documents found for this course.
            </div>
          )}
        </Card>

        <Card style={{ display: "grid", gap: 12 }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: 10,
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 600 }}>Corpus versions</div>
            <Tag color={activeCorpusVersion ? D.green : D.muted}>
              {activeCorpusVersion ? "active available" : "none active"}
            </Tag>
          </div>
          {versions.length === 0 ? (
            <div style={{ fontSize: 12, color: D.muted }}>
              No corpus versions recorded for this course yet.
            </div>
          ) : (
            <div style={{ display: "grid", gap: 8 }}>
              {versions.map((version) => (
                <Card
                  key={version.course_corpus_version_id}
                  style={{
                    padding: "12px 14px",
                    display: "grid",
                    gap: 6,
                    background: D.surface,
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      gap: 10,
                      flexWrap: "wrap",
                    }}
                  >
                    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                      <Tag
                        color={corpusVersionStatusColor(version.status, version.active)}
                      >
                        {version.active ? "active" : version.status}
                      </Tag>
                      <span style={{ fontSize: 13, fontWeight: 500 }}>
                        {version.collection_name}
                      </span>
                    </div>
                    <div style={{ ...mono, fontSize: 11, color: D.dim }}>
                      {version.course_corpus_version_id}
                    </div>
                  </div>
                  <div style={{ fontSize: 12, color: D.muted }}>
                    {typeof version.metadata.message === "string"
                      ? version.metadata.message
                      : "No status message recorded."}
                  </div>
                  <div style={{ fontSize: 11, color: D.muted }}>
                    Created {formatTimestamp(version.created_at)} · Completed{" "}
                    {formatTimestamp(version.completed_at)}
                  </div>
                </Card>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
