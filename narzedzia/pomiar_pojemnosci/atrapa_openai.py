"""Atrapa API OpenAI: embeddingi i strumień czatu z realistycznym tempem.

Aplikacja używa prawdziwego klienta `openai` (OPENAI_BASE_URL wskazuje tutaj),
więc mierzymy prawdziwą ścieżkę HTTP/SSE bez kosztów i bez danych na zewnątrz.
"""

import json
import os
import random
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PIERWSZY_TOKEN_S = float(os.getenv("PIERWSZY_TOKEN_S", "0.8"))
TOKENY = int(os.getenv("TOKENY", "250"))
ODSTEP_S = float(os.getenv("ODSTEP_S", "0.03"))
SLOWA = (
    "Nasza firma oferuje kompleksowe wsparcie w zakresie organizacji uroczystości rodzinnych"
).split()


class Atrapa(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _cialo(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def do_POST(self):
        dane = self._cialo()
        if self.path.endswith("/embeddings"):
            wymiar = int(dane.get("dimensions") or 512)
            wejscie = dane.get("input")
            ile = len(wejscie) if isinstance(wejscie, list) else 1
            cialo = json.dumps(
                {
                    "object": "list",
                    "data": [
                        {
                            "object": "embedding",
                            "index": i,
                            "embedding": [random.uniform(-1, 1) for _ in range(wymiar)],
                        }
                        for i in range(ile)
                    ],
                    "model": dane.get("model", "x"),
                    "usage": {"prompt_tokens": 12, "total_tokens": 12},
                }
            ).encode()
            time.sleep(0.15)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(cialo)))
            self.end_headers()
            self.wfile.write(cialo)
            return
        if self.path.endswith("/chat/completions"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            def wyslij(obiekt):
                linia = f"data: {json.dumps(obiekt) if obiekt != '[DONE]' else obiekt}\n\n".encode()
                self.wfile.write(f"{len(linia):x}\r\n".encode() + linia + b"\r\n")
                self.wfile.flush()

            time.sleep(PIERWSZY_TOKEN_S)
            for i in range(TOKENY):
                wyslij(
                    {
                        "id": "atrapa",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": "atrapa",
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": SLOWA[i % len(SLOWA)] + " "},
                                "finish_reason": None,
                            }
                        ],
                    }
                )
                time.sleep(ODSTEP_S)
            wyslij(
                {
                    "id": "atrapa",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "atrapa",
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 1500,
                        "completion_tokens": TOKENY,
                        "total_tokens": 1500 + TOKENY,
                    },
                }
            )
            wyslij("[DONE]")
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9000), Atrapa).serve_forever()
