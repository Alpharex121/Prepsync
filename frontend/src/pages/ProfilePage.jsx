import { useAuth } from "../context/AuthContext";

export default function ProfilePage() {
  const { user } = useAuth();

  return (
    <section className="panel animate-slide-up" style={{ maxWidth: '400px', margin: '3rem auto', textAlign: 'center' }}>
      <div className="empty-state" style={{ padding: '1rem', paddingBottom: '0' }}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ width: '80px', height: '80px', margin: '0 0 1rem 0' }}>
          <path d="M12 11c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4z"></path>
          <path d="M18 21v-2a4 4 0 0 0-4-4H10a4 4 0 0 0-4 4v2"></path>
        </svg>
      </div>
      <h3 style={{ justifyContent: 'center' }}>Welcome, {user?.username}</h3>
      <p className="muted-text" style={{ marginTop: '0' }}>Ready for your next session?</p>
    </section>
  );
}
