import { useState } from "react";

import { useAuth } from "../context/AuthContext";
import { request } from "../lib/api";

export default function HistoryPage() {
  const { user } = useAuth();

  const [mode, setMode] = useState("");
  const [topic, setTopic] = useState("");
  const [exam, setExam] = useState("");
  const [items, setItems] = useState([]);
  const [selectedRoomId, setSelectedRoomId] = useState("");
  const [report, setReport] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadHistory() {
    setError("");
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (mode) params.set("mode", mode);
      if (topic) params.set("topic", topic);
      if (exam) params.set("exam", exam);
      const query = params.toString();
      const response = await request(`/history${query ? `?${query}` : ""}`);
      setItems(response);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }

  async function openRoomReport(roomId) {
    setError("");
    setLoading(true);
    setSelectedRoomId(roomId);
    try {
      const [reportResponse, analyticsResponse] = await Promise.all([
        request(`/history/${roomId}/report?user_id=${encodeURIComponent(user.username)}`),
        request(`/history/${roomId}/analytics`),
      ]);
      setReport(reportResponse);
      setAnalytics(analyticsResponse);
    } catch (loadError) {
      setError(loadError.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="room-page">
      <h2>History & Reports</h2>

      {error ? <p className="error-text">{error}</p> : null}

      <article className="panel">
        <h3>Filters</h3>
        <div className="form-grid">
          <label>Mode</label>
          <select value={mode} onChange={(event) => setMode(event.target.value)}>
            <option value="">All</option>
            <option value="QUIZ">Quiz</option>
            <option value="TEST">Test</option>
          </select>

          <label>Topic</label>
          <input value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="Averages" />

          <label>Exam</label>
          <input value={exam} onChange={(event) => setExam(event.target.value)} placeholder="GATE" />
        </div>
        <button type="button" onClick={loadHistory} disabled={loading}>
          {loading ? "Loading..." : "Load History"}
        </button>
      </article>

      <article className="panel">
        <h3>Sessions</h3>
        {!items.length ? <p className="muted-text">No sessions loaded yet.</p> : null}
        <ul>
          {items.map((item) => (
            <li key={`${item.room_id}-${item.created_at}`}>
              <button type="button" className="link-btn" onClick={() => openRoomReport(item.room_id)}>
                {item.room_id}
              </button>{" "}
              ({item.mode}) [{item.topics.join(", ")}] [{item.exams.join(", ")}] {item.created_at}
            </li>
          ))}
        </ul>
      </article>

      {report ? (
        <article className="panel">
          <h3>Attempt Report ({selectedRoomId})</h3>
          <p className="muted-text">
            User: {report.user_id} | Mode: {report.mode}
          </p>
          <table className="report-table">
            <thead>
              <tr>
                <th>Q#</th>
                <th>Topic</th>
                <th>Selected</th>
                <th>Correct</th>
                <th>Result</th>
                <th>Time (ms)</th>
              </tr>
            </thead>
            <tbody>
              {report.attempts.map((attempt) => (
                <tr key={attempt.question_index}>
                  <td>{attempt.question_index + 1}</td>
                  <td>{attempt.topic}</td>
                  <td>{attempt.selected_option ?? "-"}</td>
                  <td>{attempt.correct_index}</td>
                  <td>{attempt.is_correct ? "Correct" : "Wrong/Unanswered"}</td>
                  <td>{attempt.time_taken_ms}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </article>
      ) : null}

      {analytics ? (
        <article className="panel">
          <h3>Room Analytics ({selectedRoomId})</h3>
          <p>
            Participants: {analytics.participant_count} | Attempts: {analytics.total_attempts} | Avg Accuracy: {(
              analytics.avg_accuracy * 100
            ).toFixed(1)}%
          </p>
          <ul>
            {analytics.section_insights.map((section) => (
              <li key={section.topic}>
                {section.topic}: {section.correct}/{section.attempted} ({(section.accuracy * 100).toFixed(1)}%)
              </li>
            ))}
          </ul>
        </article>
      ) : null}
    </section>
  );
}
