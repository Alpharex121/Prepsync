# PrepSync Frontend

## Local setup

1. Install dependencies:
   `npm install`
2. Start dev server:
   `npm run dev`

## Routes

- `/` Home
- `/login` Login/Register
- `/profile` Profile (protected)
- `/room` Room workspace (protected)
- `/history` History and reports (protected)

## Room workspace capabilities

- Create and join rooms
- Lobby controls and participant display
- Quiz mode player with countdown and answer submit
- Test mode player with section locks, palette, navigation, and section submit
- Live leaderboard and final result view
- Reconnect, loading, and error states

## History capabilities

- Session listing with mode/topic/exam filters
- Attempt report with correctness and time taken
- Section-wise insights
- Room-level analytics summary

## Available scripts

- `npm run dev`
- `npm run build`
- `npm run preview`
- `npm run lint`
- `npm run format`
