# PrepSync

A modern, real-time collaborative quiz and test preparation platform built with FastAPI and React. PrepSync enables users to create and join interactive study sessions, take quizzes and tests collaboratively, and track their learning progress with detailed analytics.

## 🚀 Features

### Core Functionality
- **Real-time Collaboration**: Join rooms for live quiz/test sessions with multiple participants
- **Dual Modes**: Quiz mode (timed questions) and Test mode (sectioned exams)
- **AI-Powered Content**: Generate custom quizzes using OpenAI, Google Gemini, or Groq
- **Authentication**: Secure JWT-based user authentication and authorization
- **Progress Tracking**: Comprehensive history and analytics for all sessions

### Room Features
- **Lobby System**: Create or join rooms with participant management
- **Live Leaderboards**: Real-time scoring and rankings during sessions
- **WebSocket Communication**: Instant updates and synchronization
- **Anti-Cheat Measures**: Duplicate answer prevention and late-submit windows

### Analytics & History
- **Session Reports**: Detailed performance analysis per attempt
- **Section-wise Insights**: Break down performance by test sections
- **Room Analytics**: Aggregate statistics for collaborative sessions
- **Filtering**: Search and filter sessions by mode, topic, and exam type

## 🏗️ Architecture

### Backend (Python/FastAPI)
- **Framework**: FastAPI with automatic OpenAPI documentation
- **Database**: PostgreSQL for persistent data, Redis for caching and real-time features
- **Authentication**: JWT tokens with bcrypt password hashing
- **Real-time**: WebSocket connections for live collaboration
- **AI Integration**: LangChain for LLM-powered quiz generation
- **Validation**: Pydantic schemas for all data models

### Frontend (React/Vite)
- **Framework**: React 18 with modern hooks
- **State Management**: Redux Toolkit for global state
- **Routing**: React Router for navigation
- **Build Tool**: Vite for fast development and optimized builds
- **Styling**: Custom CSS with modern responsive design

### Infrastructure
- **Containerization**: Docker Compose for local development
- **Databases**: PostgreSQL + Redis with health checks
- **Load Testing**: k6 scripts for performance testing
- **Code Quality**: Ruff (Python), ESLint (JavaScript), Prettier

## 📋 Prerequisites

- **Python 3.11+** (Backend)
- **Node.js 16+** (Frontend)
- **Docker & Docker Compose** (Databases)
- **Git** (Version control)

## 🛠️ Local Development Setup

### 1. Clone the Repository
```bash
git clone https://github.com/Alpharex121/Prepsync.git
cd Prepsync
```

### 2. Environment Configuration
```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your API keys for LLM providers:
# - LLM_API_KEY (OpenAI)
# - GEMINI_API_KEY (Google)
# - GROQ_API_KEY (Groq)
```

### 3. Start Databases
```bash
# Start PostgreSQL and Redis
docker-compose up -d

# Verify containers are running
docker-compose ps
```

### 4. Backend Setup
```bash
cd backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
# source venv/bin/activate

# Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Run database migrations (if needed)
# Check migrations/ directory for SQL scripts

# Start development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Backend will be available at:** `http://localhost:8000`
**API Documentation:** `http://localhost:8000/docs`

### 5. Frontend Setup
```bash
# Open new terminal
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

**Frontend will be available at:** `http://localhost:5173`

### 6. Verify Setup
- **Backend Health**: Visit `http://localhost:8000/docs`
- **Frontend**: Visit `http://localhost:5173`
- **Database**: Check Docker containers are healthy

## 🧪 Testing

### Backend Tests
```bash
cd backend

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test categories
pytest tests/test_auth.py        # Authentication tests
pytest tests/test_room_api.py    # Room API tests
pytest tests/test_websocket_integration.py  # WebSocket tests
```

### Code Quality Checks
```bash
# Python linting and formatting
ruff check .
ruff format --check .

# JavaScript linting
cd frontend && npm run lint

# Format code
cd frontend && npm run format
```

### Load Testing
```bash
# Install k6 (if not already installed)
# Run load tests
k6 run loadtest/health_load.js
```

## 📁 Project Structure

```
Prepsync/
├── backend/                    # FastAPI backend
│   ├── app/
│   │   ├── api/               # API routes
│   │   ├── core/              # Configuration & core services
│   │   ├── middleware/        # Custom middleware
│   │   ├── schemas/           # Pydantic models
│   │   ├── security/          # Authentication & security
│   │   └── services/          # Business logic
│   ├── tests/                 # Backend tests
│   ├── migrations/            # Database migrations
│   └── requirements*.txt      # Python dependencies
├── frontend/                   # React frontend
│   ├── src/
│   │   ├── components/        # Reusable components
│   │   ├── pages/            # Page components
│   │   ├── store/            # Redux store
│   │   └── lib/              # Utilities
│   └── package.json
├── shared/                     # Shared schemas/contracts
├── logs/                       # Session logs and debugging
├── loadtest/                   # Load testing scripts
├── docker-compose.yml          # Local database setup
└── .env.example               # Environment template
```

## 🔒 Security Features

- **Rate Limiting**: Prevents abuse on authentication and room actions
- **Input Validation**: Pydantic schemas validate all WebSocket and API payloads
- **Anti-Cheat**: Duplicate answer rejection and submission time windows
- **CORS Protection**: Configured origins for cross-origin requests
- **JWT Authentication**: Secure token-based authentication

## 📊 Observability

- **Request Logging**: Structured logging middleware for all HTTP requests
- **Error Tracking**: Comprehensive error logging and handling
- **Metrics**: In-memory counters for monitoring key operations
- **Health Checks**: Database connectivity and service health endpoints

## 🚀 Deployment

### Production Environment Variables
```bash
APP_ENV=production
JWT_SECRET_KEY=<strong-random-key>
LLM_API_KEY=<your-api-key>
POSTGRES_HOST=<production-db-host>
REDIS_HOST=<production-redis-host>
```

### Docker Deployment
```bash
# Build and run with Docker Compose
docker-compose -f docker-compose.prod.yml up -d
```

### Frontend Deployment
```bash
cd frontend
npm run build
# Deploy dist/ directory to your hosting service (Vercel, Netlify, etc.)
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes with tests
4. Run quality checks: `ruff check .` and `npm run lint`
5. Commit your changes: `git commit -am 'Add new feature'`
6. Push to the branch: `git push origin feature/your-feature`
7. Submit a pull request

## 📝 API Documentation

Once the backend is running, visit `http://localhost:8000/docs` for interactive API documentation powered by Swagger UI.

### Key Endpoints
- `POST /auth/login` - User authentication
- `POST /auth/register` - User registration
- `POST /rooms` - Create new room
- `GET /rooms/{room_id}` - Get room details
- `GET /history` - Get user session history
- `WebSocket /ws/rooms/{room_id}` - Real-time room communication

## 🐛 Troubleshooting

### Common Issues

**Backend won't start:**
- Ensure Python 3.11+ is installed
- Check virtual environment is activated
- Verify database containers are running: `docker-compose ps`

**Frontend build fails:**
- Clear node_modules: `rm -rf node_modules && npm install`
- Check Node.js version: `node --version`

**Database connection errors:**
- Ensure Docker containers are healthy
- Check .env database configuration
- Verify ports aren't in use by other services

**WebSocket connections fail:**
- Check CORS settings in .env
- Ensure backend is running on correct host/port
- Verify firewall settings

### Logs and Debugging
- **Backend logs**: Check terminal output or `logs/` directory
- **Frontend logs**: Browser developer console
- **Database logs**: `docker-compose logs postgres redis`

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/) and [React](https://reactjs.org/)
- AI powered by [LangChain](https://www.langchain.com/)
- UI components inspired by modern design systems
- Testing framework: [pytest](https://pytest.org/) and [k6](https://k6.io/)

---

**Happy Learning! 🎓**
