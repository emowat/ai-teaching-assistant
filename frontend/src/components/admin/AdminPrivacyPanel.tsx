import { useEffect, useState } from "react";
import {
  type AdminReportedIssue,
  type AdminDataDeletionRequest,
  fetchAdminReportedIssues,
  fetchAdminDataDeletionRequests,
  scrubAdminUserData,
  resolveAdminReportedIssue,
} from "../../api/adminUsersApi";
import { Btn, Card } from "../../design/atoms";

export function AdminPrivacyPanel({ accessToken }: { accessToken: string }) {
  const [issues, setIssues] = useState<AdminReportedIssue[]>([]);
  const [requests, setRequests] = useState<AdminDataDeletionRequest[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedChatIssue, setSelectedChatIssue] = useState<AdminReportedIssue | null>(null);

  useEffect(() => {
    loadData();
  }, []);

  async function loadData() {
    setLoading(true);
    try {
      const [issuesRes, requestsRes] = await Promise.all([
        fetchAdminReportedIssues(accessToken),
        fetchAdminDataDeletionRequests(accessToken),
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

  async function handleScrub(requestId: string) {
    if (!window.confirm("Are you sure you want to scrub this user's data? This cannot be undone.")) return;
    try {
      await scrubAdminUserData(requestId, accessToken);
      alert("User data scrubbed successfully.");
      loadData();
    } catch (err: any) {
      alert("Failed to scrub data: " + err.message);
    }
  }

  async function handleResolveIssue(issueId: string) {
    try {
      await resolveAdminReportedIssue(issueId, accessToken);
      loadData();
    } catch (err: any) {
      alert("Failed to resolve issue: " + err.message);
    }
  }

  if (loading) return <div>Loading...</div>;

  return (
    <>
      <div style={{ display: "flex", flexDirection: "column", gap: "32px" }}>
      <h2>Privacy & Ethics</h2>
      
      <Card>
        <h3>Red Flags (Reported Issues)</h3>
        {issues.length === 0 ? (
          <p>No reported issues.</p>
        ) : (
          <table style={{ width: "100%", textAlign: "left", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #ccc" }}>
                <th>Date</th>
                <th>Professor</th>
                <th>Section</th>
                <th>Reason</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {issues.map(issue => (
                <tr key={issue.issue_id} style={{ borderBottom: "1px solid #eee" }}>
                  <td>{new Date(issue.created_at).toLocaleString()}</td>
                  <td>{issue.professor_email || "Unknown"}</td>
                  <td>{issue.section_name || issue.section_id || "Unknown"}</td>
                  <td>{issue.reason}</td>
                  <td>{issue.status}</td>
                  <td>
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <Btn onClick={() => setSelectedChatIssue(issue)}>View Chat</Btn>
                      {issue.status === 'open' && (
                        <Btn 
                          onClick={() => handleResolveIssue(issue.issue_id)}
                          style={{ background: "#4caf50", color: "white", border: "none" }}
                        >
                          Acknowledge
                        </Btn>
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
          <p>No deletion requests.</p>
        ) : (
          <table style={{ width: "100%", textAlign: "left", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #ccc" }}>
                <th>Date</th>
                <th>Professor</th>
                <th>Section</th>
                <th>Status</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {requests.map(req => (
                <tr key={req.request_id} style={{ borderBottom: "1px solid #eee" }}>
                  <td>{new Date(req.created_at).toLocaleString()}</td>
                  <td>{req.professor_email || "Unknown"}</td>
                  <td>{req.section_name || "Unknown"}</td>
                  <td>{req.status}</td>
                  <td>
                    {req.status === "pending_professor_approval" ? (
                      <Btn onClick={() => handleScrub(req.request_id)}>Scrub Data</Btn>
                    ) : (
                      "Scrubbed"
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
          <div style={{ background: "white", width: "600px", maxHeight: "80vh", borderRadius: "8px", display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 4px 12px rgba(0,0,0,0.15)" }}>
            <div style={{ padding: "16px", borderBottom: `1px solid #ccc`, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h3 style={{ margin: 0 }}>Chat History (Issue #{selectedChatIssue.issue_id.substring(0, 8)})</h3>
              <button onClick={() => setSelectedChatIssue(null)} style={{ background: "transparent", border: "none", cursor: "pointer", fontSize: "16px" }}>✕</button>
            </div>
            <div style={{ padding: "16px", overflowY: "auto", flex: 1, display: "flex", flexDirection: "column", gap: "12px" }}>
              {selectedChatIssue.chat_history.map((msg, i) => (
                <div key={i} style={{ 
                  alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  background: msg.role === 'user' ? '#0070f3' : '#f5f5f5',
                  color: msg.role === 'user' ? '#fff' : '#333',
                  padding: '8px 12px',
                  borderRadius: '8px',
                  maxWidth: '80%',
                  border: msg.role !== 'user' ? `1px solid #ddd` : 'none'
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
