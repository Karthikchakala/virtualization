#!/usr/bin/env python3
"""
http_health_app.py - Minimal identical HTTP application for CC2 application latency benchmarking.

Handles:
- GET /health -> HTTP 200 OK, Content-Type: application/json, body: {"status":"healthy"}
- All other endpoints -> HTTP 404 Not Found
- Zero third-party dependencies (pure standard library).
"""

import sys
import json
import argparse
import http.server
import socketserver
from typing import Optional

class HealthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            body = b'{"status":"healthy","app":"cc2_health_benchmark","code":200}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress access logs during high-throughput benchmarking
        pass

def run_server(host: str = "0.0.0.0", port: int = 8080):
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer((host, port), HealthHandler) as httpd:
        actual_port = httpd.server_address[1]
        print(f"CC2_HTTP_SERVER_READY host={host} port={actual_port}", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CC2 Minimal Identical Health HTTP Application")
    parser.add_argument("--host", default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080, 0 for dynamic)")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)
