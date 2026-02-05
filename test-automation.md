# Test Automation

This document explains how to run automated API checks with timeouts so hangs don't block you.

## Prerequisites

- Server running on `http://127.0.0.1:6684`
- A working input device (e.g., MacBook Pro Microphone)

## Quick Status Check

```bash
curl --max-time 5 --connect-timeout 2 -s http://127.0.0.1:6684/api/health
curl --max-time 5 --connect-timeout 2 -s http://127.0.0.1:6684/api/recording/status
```

## Automated Start/Stop (with timeouts)

```bash
DEVICE_INDEX=0

curl --max-time 5 --connect-timeout 2 -s http://127.0.0.1:6684/api/audio/devices

curl --max-time 5 --connect-timeout 2 -s -X POST http://127.0.0.1:6684/api/recording/start \
  -H "Content-Type: application/json" \
  -d "{\"device_index\": ${DEVICE_INDEX}, \"samplerate\": 48000, \"channels\": 1}"

sleep 3

curl --max-time 5 --connect-timeout 2 -s -X POST http://127.0.0.1:6684/api/recording/stop

curl --max-time 5 --connect-timeout 2 -s http://127.0.0.1:6684/api/recording/status
```

## If a Command Hangs

- `curl --max-time 5` ensures it times out.
- Check logs:
  - `logs/server_*.log`
  - `logs/crash.log`

## Debugging Checklist

1. Confirm server is running: `lsof -i :6684`
2. Check latest server log for:
   - `start_recording received`
   - `start_recording completed in ... ms`
   - `stop_recording received`
   - `stop_recording completed in ... ms`
3. If missing, capture the new logs and follow `current-debug-session.md`.
