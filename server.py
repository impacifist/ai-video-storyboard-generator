"""Dependency-free, loopback-only development application."""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from storyboard import conversion, engine, guides, library, providers, references
from storyboard.schema import ValidationError, validate_brief

ROOT = Path(__file__).resolve().parent
BUSY = threading.Lock()
MAX_BODY = 16_000_000


class Handler(BaseHTTPRequestHandler):
    server_version = "PersonaStoryboard/0.1"

    def log_message(self, format, *args):
        # No request bodies, model output, query strings, or credentials in logs.
        pass

    def allowed(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            self.send_json({"error": "허용되지 않은 호스트입니다."}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {f"http://{h}" for h in hosts}:
            self.send_json({"error": "다른 사이트에서의 요청은 허용하지 않습니다."}, 403)
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send_json({"error": "다른 사이트에서의 요청은 허용하지 않습니다."}, 403)
            return False
        return True

    def send_bytes(self, data, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; "
                         "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
                         "frame-ancestors 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, value, status=200):
        self.send_bytes(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                        "application/json; charset=utf-8", status)

    def do_GET(self):
        if not self.allowed():
            return
        if self.path == "/api/config":
            try:
                self.send_json(providers.configuration())
            except (ValidationError, ValueError, UnicodeError, OSError):
                self.send_json({"error": "로컬 API 설정을 읽을 수 없습니다. 설정 파일 형식과 접근 권한을 확인해주세요."}, 500)
        elif self.path == "/api/example":
            self.send_bytes((ROOT / "examples" / "rainy-classroom.json").read_bytes(),
                            "application/json; charset=utf-8")
        elif self.path == "/api/guides":
            self.send_json({"guides": guides.catalog()})
        elif self.path.startswith(("/api/references/image/", "/api/conversion/package/")):
            try:
                key = self.path.rsplit("/", 1)[-1]
                if self.path.startswith("/api/references/image/"):
                    asset = references.asset(key)
                    self.send_bytes(asset["data"], asset["mime"])
                else:
                    self.send_bytes(references.package(key), "application/zip")
            except ValidationError as exc:
                self.send_json({"error": str(exc)}, 400)
        else:
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/translations.js": ("translations.js", "text/javascript; charset=utf-8"),
                     "/i18n.js": ("i18n.js", "text/javascript; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8")}
            if self.path not in files:
                self.send_json({"error": "찾을 수 없습니다."}, 404)
                return
            name, content_type = files[self.path]
            self.send_bytes((ROOT / "web" / name).read_bytes(), content_type)

    def do_POST(self):
        if not self.allowed():
            return
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            self.send_json({"error": "JSON 요청만 허용합니다."}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        body_limit = 6_800_000 if self.path == "/api/references/upload" else MAX_BODY
        if not 0 < length <= body_limit:
            self.send_json({"error": "이미지 형식과 5MB 이하 크기를 확인해주세요." if self.path == "/api/references/upload"
                            else "요청은 16MB 이내여야 합니다."}, 413)
            return
        try:
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValidationError("JSON 객체가 필요합니다.")
            if self.path == "/api/library/list":
                self.send_json({"items": library.listing(payload.get("deleted", False))})
            elif self.path == "/api/library/save":
                self.send_json({"saved": library.save(payload.get("document"))})
            elif self.path == "/api/library/load":
                document = library.load(payload.get("id"))
                self.send_json({"document": document, "review": engine.review(document),
                                "conversions": library.conversions(payload.get("id")),
                                "references": references.load(payload.get("id"))})
            elif self.path == "/api/references/upload":
                self.send_json({"asset": references.upload(payload)})
            elif self.path == "/api/references/save":
                self.send_json({"references": references.save(payload.get("id"), payload.get("references"))})
            elif self.path in ("/api/library/delete", "/api/library/restore"):
                library.trash(payload.get("id"), self.path.endswith("/delete"))
                self.send_json({"ok": True})
            elif self.path == "/api/conversion/plan":
                self.send_json({"plan": conversion.preflight(library.load(payload.get("id")), payload)[0]})
            elif self.path == "/api/conversion/compile":
                if not BUSY.acquire(blocking=False):
                    self.send_json({"error": "다른 생성·검수가 진행 중입니다."}, 409)
                    return
                try:
                    result = conversion.compile_prompts(library.load(payload.get("id")), payload)
                    saved_id = library.save_conversion(payload.get("id"), result)
                    if result.get("references"):
                        references.save(payload.get("id"), payload.get("references", []))
                    self.send_json({"result": result, "id": saved_id})
                finally:
                    BUSY.release()
            elif self.path == "/api/settings":
                if not BUSY.acquire(blocking=False):
                    self.send_json({"error": "생성·검수가 끝난 뒤 설정을 변경해주세요."}, 409)
                    return
                try:
                    self.send_json(providers.save_settings(payload))
                finally:
                    BUSY.release()
            elif self.path == "/api/generate":
                if not BUSY.acquire(blocking=False):
                    self.send_json({"error": "다른 생성·검수가 진행 중입니다."}, 409)
                    return
                try:
                    document = engine.generate(payload)
                    self.send_json({"document": document, "review": engine.review(document)})
                finally:
                    BUSY.release()
            elif self.path == "/api/validate":
                if "document" in payload:
                    self.send_json({"review": engine.review(payload["document"])})
                else:
                    validate_brief(payload.get("brief"))
                    self.send_json({"valid": True})
            elif self.path == "/api/review":
                if not BUSY.acquire(blocking=False):
                    self.send_json({"error": "다른 생성·검수가 진행 중입니다."}, 409)
                    return
                try:
                    self.send_json({"ai_review": engine.semantic_review(payload.get("document"),
                                    payload.get("provider"), payload.get("model", ""))})
                finally:
                    BUSY.release()
            elif self.path == "/api/export":
                self.send_json({"markdown": engine.markdown(payload.get("document"))})
            else:
                self.send_json({"error": "찾을 수 없습니다."}, 404)
        except (ValidationError, json.JSONDecodeError, UnicodeError) as exc:
            message = str(exc) if isinstance(exc, ValidationError) else "올바른 UTF-8 JSON이 필요합니다."
            self.send_json({"error": message}, 400)
        except providers.ProviderError as exc:
            self.send_json({"error": str(exc)}, 502)
        except Exception:
            self.send_json({"error": "처리 중 오류가 발생했습니다. 기존 콘티는 유지됩니다."}, 500)


def main():
    parser = argparse.ArgumentParser(description="Persona Storyboard local studio")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Persona Storyboard: http://127.0.0.1:{server.server_port}", flush=True)
    print("Stop: Ctrl+C. API calls happen only when requested in the UI.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
