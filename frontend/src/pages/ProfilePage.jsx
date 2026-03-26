import { useAuth } from "../context/AuthContext";

export default function ProfilePage() {
  const { user } = useAuth();

  return (
    <section className="panel animate-slide-up" style={{ maxWidth: '600px', margin: '2rem auto' }}>
      <h3>Profile</h3>
      <p className="muted-text">Logged in as: <strong className="text-primary">{user?.username}</strong></p>
    </section>
  );
}
