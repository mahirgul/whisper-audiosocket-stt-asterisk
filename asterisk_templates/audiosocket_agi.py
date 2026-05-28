#!/usr/bin/env python3
"""
WASA — Asterisk Python AGI Script Template (audiosocket_agi.py)

This script demonstrates how to read channel variables and dynamically
stream call audio to the AudioSocket server using Asterisk AGI.
"""

import sys

def send_agi_command(command: str) -> str:
    """Send command to Asterisk via stdout and read response."""
    sys.stdout.write(f"{command}\n")
    sys.stdout.flush()
    return sys.stdin.readline().strip()

def main():
    # Read AGI Environment Variables sent by Asterisk on startup
    agi_env = {}
    while True:
        line = sys.stdin.readline().strip()
        if not line:
            break
        key, val = line.split(":", 1)
        agi_env[key.strip()] = val.strip()

    # Log to Asterisk Console
    send_agi_command("VERBOSE \"WASA Python AGI Initialized...\" 1")

    # Fetch unique ID and other info
    unique_id = agi_env.get("agi_uniqueid", "unknown-uuid")
    send_agi_command(f"VERBOSE \"Processing Call UniqueID: {unique_id}\" 1")

    # Connect the call to the AudioSocket server (Port 9092)
    # Syntax: EXEC AudioSocket <uuid>,<host:port>
    server_address = "127.0.0.1:9092"
    
    # Generate a matching UUID for the AudioSocket connection
    import uuid
    session_uuid = str(uuid.uuid4())

    send_agi_command(f"VERBOSE \"Routing call {unique_id} to AudioSocket {server_address} with Session UUID: {session_uuid}\" 1")
    send_agi_command(f"EXEC AudioSocket {session_uuid},{server_address}")

    # AudioSocket has finished (call hung up or connection closed)
    send_agi_command("VERBOSE \"AudioSocket connection ended. AGI script exiting.\" 1")

if __name__ == "__main__":
    main()
