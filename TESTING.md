# Testing

## Phase 0 — Server Skeleton

1. Start the server: `/Users/chee/projects/notetaker/notetaker.sh`
2. Open http://localhost:6684  
   Expected: `{"message":"Notetaker API running"}`
3. Open http://localhost:6684/api/health  
   Expected: `{"status":"ok"}`

## Phase 1 — Audio Capture (API)

1. Start the server: `/Users/chee/projects/notetaker/notetaker.sh`
2. List devices:
   - `curl -s http://127.0.0.1:6684/api/audio/devices`
   - Find your virtual audio device index (BlackHole or VB-Cable)
3. Start recording:
   - `curl -s -X POST http://127.0.0.1:6684/api/recording/start -H "Content-Type: application/json" -d '{"device_index": <INDEX>}'`
4. Play audio on your computer for ~10 seconds
5. Stop recording:
   - `curl -s -X POST http://127.0.0.1:6684/api/recording/stop`
6. Verify a WAV file appears under `data/recordings/` and plays back with the recorded audio
