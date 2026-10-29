"""A microscope, not a client. Stdio is hand rolled and both directions are printed.

Run:  uv run python raw_client.py
"""

import json
import subprocess
import sys

META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}

LIMIT = 400


def _short(text):
    if len(text) <= LIMIT:
        return text
    return f"{text[:LIMIT]}... ({len(text)} chars)"


def send(proc, obj):
    line = json.dumps(obj)
    print("-->", _short(line))
    proc.stdin.write(line + "\n")
    proc.stdin.flush()
    reply = proc.stdout.readline().strip()
    print("<--", _short(reply))
    print()
    return json.loads(reply)


def open_server():
    return subprocess.Popen(
        [sys.executable, "server_flights.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def demo_modern():
    print("=== server/discover first, then tools/list          (modern) ===")
    proc = open_server()
    send(proc, {"jsonrpc": "2.0", "id": 1, "method": "server/discover", "params": {"_meta": META}})
    send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": META}})
    proc.kill()


def demo_legacy():
    print("=== initialize first, then the same tools/list        (legacy) ===")
    proc = open_server()
    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "capabilities": {},
                "clientInfo": {"name": "raw_client", "version": "0.1.0"},
            },
        },
    )
    send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"_meta": META}})
    proc.kill()


def demo_no_meta():
    print("=== dropping _meta breaks every request ===")
    proc = open_server()
    send(proc, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    proc.kill()


def demo_call():
    print("=== the whole round trip, tools/call ===")
    proc = open_server()
    send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search_flights",
                "arguments": {
                    "slices": [
                        {"origin": "BOM", "destination": "DEL", "departure_date": "2026-11-12"}
                    ]
                },
                "_meta": META,
            },
        },
    )
    proc.kill()


if __name__ == "__main__":
    demo_modern()
    demo_legacy()
    demo_no_meta()
    demo_call()