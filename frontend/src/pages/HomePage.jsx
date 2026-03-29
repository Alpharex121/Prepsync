import { Link } from "react-router-dom";

export default function HomePage() {
  return (
    <section className="split-hero animate-slide-up">
      <div className="hero-content">
        <h2 className="hero-title">Real-time exam preparation rooms</h2>
        <p className="hero-subtitle animate-delay-1">
          Create or join a room to compete in synchronized quiz and test sessions.
        </p>
        <div className="hero-actions animate-delay-2">
          <Link to="/room" className="hero-btn">
            Open Room Workspace
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
          </Link>
        </div>
      </div>
      <div className="hero-vector animate-delay-3">
        {/* Abstract 3D/Tech SVG Vector Graphic */}
        <svg viewBox="0 0 500 500" fill="none" xmlns="http://www.w3.org/2000/svg">
          <circle cx="250" cy="250" r="150" fill="url(#paint0_linear)" fillOpacity="0.8"/>
          <path d="M250 80C343.888 80 420 156.112 420 250H80C80 156.112 156.112 80 250 80Z" fill="url(#paint1_linear)"/>
          <rect x="210" y="160" width="80" height="180" rx="40" fill="#fff" fillOpacity="0.2" className="animate-pulse"/>
          <circle cx="250" cy="280" r="20" fill="#8b5cf6" />
          <path opacity="0.5" d="M120 250C120 178.197 178.197 120 250 120" stroke="url(#paint2_linear)" strokeWidth="4" strokeLinecap="round" strokeDasharray="10 20">
            <animateTransform attributeName="transform" type="rotate" from="0 250 250" to="360 250 250" dur="20s" repeatCount="indefinite" />
          </path>
          <path opacity="0.3" d="M250 380C321.803 380 380 321.803 380 250" stroke="url(#paint2_linear)" strokeWidth="4" strokeLinecap="round" strokeDasharray="10 20">
             <animateTransform attributeName="transform" type="rotate" from="360 250 250" to="0 250 250" dur="20s" repeatCount="indefinite" />
          </path>
          <defs>
            <linearGradient id="paint0_linear" x1="100" y1="100" x2="400" y2="400" gradientUnits="userSpaceOnUse">
              <stop stopColor="#8b5cf6"/>
              <stop offset="1" stopColor="#3b82f6"/>
            </linearGradient>
            <linearGradient id="paint1_linear" x1="250" y1="80" x2="250" y2="250" gradientUnits="userSpaceOnUse">
              <stop stopColor="#ec4899" stopOpacity="0.8"/>
              <stop offset="1" stopColor="#8b5cf6" stopOpacity="0"/>
            </linearGradient>
            <linearGradient id="paint2_linear" x1="120" y1="120" x2="380" y2="380" gradientUnits="userSpaceOnUse">
              <stop stopColor="#fff"/>
              <stop offset="1" stopColor="#fff" stopOpacity="0"/>
            </linearGradient>
          </defs>
        </svg>
      </div>
    </section>
  );
}
