import { useEffect, useState } from "react";
import {
  type ProfessorReportedIssue,
  type ProfessorDataDeletionRequest,
  fetchProfessorReportedIssues,
  fetchProfessorDataDeletionRequests,
  resolveProfessorReportedIssue,
  scrubProfessorUserData,
} from "../../api/professorSectionsApi";
import { Card } from "../../design/atoms";
import { D } from "../../design/tokens";

export function ProfessorPrivacyPanel({ accessToken, sectionId }: { accessToken: string, sectionId: string }) {
  const [issues, setIssues] = useState<ProfessorReportedIssue[]>([]);
  const [requests, setRequests] = useState<ProfessorDataDeletionRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedChatIssue, setSelectedChatIssue] = useState<ProfessorReportedIssue | null>(null);

  async function handleResolveIssue(issueId: string) {
    if (!sectionId) return;
    try {
      await resolveProfessorReportedIssue(sectionId, issueId, accessToken);
      loadData();
    } catch (err: any) {
      alert("Failed to resolve issue: " + err.message);
    }
  }

  useEffect(() => {
    if (!sectionId) return;
    loadData();
  }, [sectionId]);

  async function loadData() {
    setLoading(true);
    try {
      const [issuesRes, requestsRes] = await Promise.all([
        fetchProfessorReportedIssues(sectionId, accessToken),
        fetchProfessorDataDeletionRequests(sectionId, accessToken),
      ]);
      setIssues(issuesRes.issues);
      setRequests(requestsRes.requests);
    } catch (e) {
      console.error(e);
      alert("Failed to load privacy data.");
    } finally {
      setLoading(false);
    }
  }

  if (!sectionId) return <div>Please select a section first.</div>;
  if (loading) return <div>Loading...</div>;

  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: "32px" }}>
      <div>
        <h2 style={{ marginBottom: "8px" }}>Privacy & Ethics</h2>
        <p style={{ color: D.muted, fontSize: "14px" }}>
          This data allows you to review reported issues and manage data deletion requests.
        </p>
      </div>
      
      <Card>
        <h3>Red Flags (Reported Issues)</h3>
        {issues.length === 0 ? (
          <p>No reported issues for this section.</p>
        ) : (
          <table style={{ width: "100%", textAlign: "left", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #ccc" }}>
                <th>Date</th>
                <th>Student</th>
                <th>Reason</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {issues.map(issue => (
                <tr key={issue.issue_id} style={{ borderBottom: "1px solid #eee" }}>
                  <td>{new Date(issue.created_at).toLocaleString()}</td>
                  <td>{issue.student_email}</td>
                  <td>{issue.reason}</td>
                  <td>{issue.status}</td>
                  <td>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button 
                        onClick={() => setSelectedChatIssue(issue)}
                        style={{
                          background: D.blue, color: "white", padding: "4px 8px",
                          borderRadius: "4px", border: "none", cursor: "pointer"
                        }}
                      >
                        View Chat
                      </button>
                      {issue.status === 'open' && (
                        <button 
                          onClick={() => handleResolveIssue(issue.issue_id)}
                          style={{
                            background: "#4caf50", color: "white", padding: "4px 8px",
                            borderRadius: "4px", border: "none", cursor: "pointer"
                          }}
                        >
                          Acknowledge
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card>
        <h3>Data Deletion Requests (Consent Withdrawn)</h3>
        {requests.length === 0 ? (
          <p>No deletion requests for this section.</p>
        ) : (
          <table style={{ width: "100%", textAlign: "left", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #ccc" }}>
                <th>Date</th>
                <th>Student</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {requests.map(req => (
                <tr key={req.request_id} style={{ borderBottom: "1px solid #eee" }}>
                  <td>{new Date(req.created_at).toLocaleString()}</td>
                  <td>{req.student_email}</td>
                  <td>{req.status}</td>
                  <td>
                    {req.status === 'pending_professor_approval' && (
                      <button
                        onClick={async () => {
                          if (!window.confirm("Are you sure you want to scrub this user's data? This cannot be undone.")) return;
                          try {
                            await scrubProfessorUserData(sectionId, req.user_id, accessToken);
                            alert("User data scrubbed successfully.");
                            loadData();
                          } catch (e) {
                            console.error(e);
                            alert("Failed to scrub data.");
                          }
                        }}
                        style={{
                          background: "#dc2626", color: "white", padding: "4px 8px",
                          borderRadius: "4px", border: "none", cursor: "pointer"
                        }}
                      >
                        Scrub Data
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
      
      {selectedChatIssue && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }}>
          <div style={{ background: D.card, width: "600px", maxHeight: "80vh", borderRadius: "8px", display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 4px 12px rgba(0,0,0,0.15)" }}>
            <div style={{ padding: "16px", borderBottom: `1px solid ${D.border}`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>Chat History for {selectedChatIssue.student_email}</h3>
              <button onClick={() => setSelectedChatIssue(null)} style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: "16px", color: D.text }}>✕</button>
            </div>
            <div style={{ padding: "16px", overflowY: "auto", flex: 1, display: "flex", flexDirection: "column", gap: "12px" }}>
              {selectedChatIssue.chat_history.map((msg, i) => (
                <div key={i} style={{ 
                  alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  background: msg.role === 'user' ? D.blue : D.bg,
                  color: msg.role === 'user' ? '#fff' : D.text,
                  padding: '8px 12px',
                  borderRadius: '8px',
                  maxWidth: '80%',
                  border: msg.role !== 'user' ? `1px solid ${D.border}` : 'none'
                }}>
                  <div style={{ fontSize: '11px', opacity: 0.7, marginBottom: '4px', textTransform: 'capitalize' }}>{msg.role}</div>
                  <div style={{ whiteSpace: 'pre-wrap', fontSize: '13px' }}>{msg.content}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
