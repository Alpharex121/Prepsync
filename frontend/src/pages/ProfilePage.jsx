import { useAuth } from "../context/AuthContext";

export default function ProfilePage() {
  const { user } = useAuth();

  return (
    <section>
      <h2>Profile</h2>
      <p>Logged in as: {user?.username}</p>
    </section>
  );
}
