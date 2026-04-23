"""
test1.py

DEPRECATED — This file is no longer used.

Kept for reference only.  Safe to delete.
"""

import socket
import struct
import threading
import wave
import os
import uuid as uuidlib
from datetime import datetime

HOST = "0.0.0.0"
PORT = 4000

SAVE_WAV = True
OUTPUT_DIR = "./records"

os.makedirs(OUTPUT_DIR, exist_ok=True)


def recv_exact(conn, size):
    data = b''
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


class AudioStream:
    def __init__(self, uuid):
        self.uuid = uuid
        self.buffer = bytearray()
        self.start_time = datetime.now()

        if SAVE_WAV:
            filename = os.path.join(OUTPUT_DIR, f"{uuid}.wav")
            self.wav = wave.open(filename, "wb")
            self.wav.setnchannels(1)
            self.wav.setsampwidth(2)  # 16-bit
            self.wav.setframerate(8000)
        else:
            self.wav = None

        print(f"[+] Stream started: {uuid}")

    def write(self, data):
        if self.wav:
            self.wav.writeframes(data)

        self.buffer.extend(data)

        # 🔥 örnek: chunk bazlı işlem
        if len(self.buffer) >= 32000:  # ~1 saniye
            chunk = bytes(self.buffer)
            self.buffer.clear()

            # burada whisper çağırabilirsin
            # print(f"[DEBUG] {self.uuid} chunk ready ({len(chunk)} bytes)")

    def close(self):
        if self.wav:
            self.wav.close()

        print(f"[+] Stream closed: {self.uuid}")


def handle_client(conn, addr):
    print(f"[+] Connection from {addr}")

    stream = None

    try:
        while True:
            header = recv_exact(conn, 3)
            if not header:
                break

            msg_type = header[0]
            length = struct.unpack(">H", header[1:])[0]

            payload = recv_exact(conn, length)
            if payload is None:
                break

            # UUID packet
            if msg_type == 0x01:
                try:
                    parsed_uuid = str(uuidlib.UUID(bytes=payload))
                except Exception:
                    parsed_uuid = payload.hex()

                print(f"[+] UUID: {parsed_uuid}")
                stream = AudioStream(parsed_uuid)

            # Audio packet
            elif msg_type == 0x10:
                if stream:
                    stream.write(payload)

            else:
                print(f"[!] Unknown packet type: {msg_type}")

    except Exception as e:
        print(f"[!] Error: {e}")

    finally:
        if stream:
            stream.close()

        conn.close()
        print(f"[-] Disconnected {addr}")


def start_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # 🔥 önemli: restart sonrası port reuse
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    s.bind((HOST, PORT))
    s.listen(20)

    print(f"[+] AudioSocket server listening on {HOST}:{PORT}")

    while True:
        conn, addr = s.accept()

        t = threading.Thread(target=handle_client, args=(conn, addr))
        t.daemon = True
        t.start()


if __name__ == "__main__":
    start_server()