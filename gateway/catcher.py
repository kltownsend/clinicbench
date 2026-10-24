"""Local stand-in for api.anthropic.com: prints what LiteLLM sends (key redacted) and returns a
canned Messages response, so the gateway's request can be read before anything is spent."""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        safe = ("content-type", "content-length", "anthropic-version", "anthropic-beta", "user-agent", "accept")
        hdr = {k: (v if k.lower() in safe else "<redacted>") for k, v in self.headers.items()}
        print(json.dumps({"path": self.path, "headers": hdr, "body": body}, indent=1), flush=True)
        out = {"id": "msg_x", "type": "message", "role": "assistant", "model": body.get("model"),
               "content": [{"type": "text", "text": '{"answer": "yes"}'}], "stop_reason": "end_turn",
               "usage": {"input_tokens": 100, "output_tokens": 8}}
        data = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
