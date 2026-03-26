import { Link } from "react-router-dom";

export default function HomePage() {
  return (
    <section>
      <h2>Real-time exam preparation rooms</h2>
      <p>Create or join a room to compete in synchronized quiz and test sessions.</p>
      <p>
        <Link to="/room">Open Room Workspace</Link>
      </p>
    </section>
  );
}
