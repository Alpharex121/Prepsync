import { Link } from "react-router-dom";

export default function HomePage() {
  return (
    <section className="hero-section animate-slide-up">
      <h2 className="hero-title">Real-time exam preparation rooms</h2>
      <p className="hero-subtitle animate-delay-1">
        Create or join a room to compete in synchronized quiz and test sessions.
      </p>
      <div className="hero-actions animate-delay-2">
        <Link to="/room" className="hero-btn">Open Room Workspace</Link>
      </div>
    </section>
  );
}
