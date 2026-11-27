"""Local stand-in for the Anthropic Messages API, served by Claude Code headless (claude -p).

Lets reqcheck's LLM_PROVIDER=anthropic run on a Claude Code subscription instead of an API key:
    python tools/claude_proxy.py 8765
    ANTHROPIC_BASE_URL=http://127.0.0.1:8765 LLM_PROVIDER=anthropic python -m reqcheck ...
Binds to 127.0.0.1 only.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CLAUDE = shutil.which("claude") or "claude"


def run_claude(model: str, system: str, user: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "system.txt"
        sp.write_text(system, encoding="utf-8")
        cmd = [CLAUDE, "-p", "--output-format", "json", "--model", model, "--system-prompt-file", str(sp),
               "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence"]
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, encoding="utf-8", cwd=tmp, timeout=1800)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"is_error": True, "result": (proc.stderr or proc.stdout or "no output")[-500:]}


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("proxy: " + fmt % args + "\n")

    def sse(self, event: str, data: dict):
        self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
        self.wfile.flush()

    def do_POST(self):
        if not self.path.startswith("/v1/messages"):
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        model = body.get("model", "")
        system = text_of(body.get("system", ""))
        user = "\n\n".join(text_of(m.get("content", "")) for m in body.get("messages", []) if m.get("role") == "user")

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        self.sse("message_start", {"type": "message_start", "message": {
            "id": "msg_local", "type": "message", "role": "assistant", "model": model, "content": [],
            "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}})

        box = {}
        worker = threading.Thread(target=lambda: box.update(out=run_claude(model, system, user)))
        worker.start()
        while worker.is_alive():
            worker.join(15)
            if worker.is_alive():
                self.sse("ping", {"type": "ping"})
        out = box.get("out") or {"is_error": True, "result": "no output"}

        if out.get("is_error"):
            msg = str(out.get("result", ""))
            kind = "rate_limit_error" if "limit" in msg.lower() else "overloaded_error"
            self.sse("error", {"type": "error", "error": {"type": kind, "message": msg[:500]}})
            return
        u = out.get("usage") or {}
        tokens_in = sum(u.get(k, 0) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        self.sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
        self.sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": str(out.get("result", ""))}})
        self.sse("content_block_stop", {"type": "content_block_stop", "index": 0})
        self.sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                   "usage": {"input_tokens": tokens_in, "output_tokens": u.get("output_tokens", 0) or 0}})
        self.sse("message_stop", {"type": "message_stop"})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
