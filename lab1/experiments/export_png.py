"""SVG → PNG через браузер (для отчёта .docx).

Нативные библиотеки растеризации (matplotlib, cairo, FreeType в Pillow) на этой
машине блокирует Smart App Control, а браузер рисует SVG сам. Скрипт поднимает
локальный сервер: страница рисует каждый SVG на canvas (×2) и отправляет PNG
обратно, сервер сохраняет их в experiments/figures/png/.

    python experiments/export_png.py      → открыть http://localhost:8765
"""
from __future__ import annotations

import http.server
import json
from pathlib import Path

FIG = Path(__file__).resolve().parent / "figures"
OUT = FIG / "png"
PORT = 8765

PAGE = """<!doctype html><meta charset="utf-8"><title>SVG → PNG</title>
<body style="font-family:sans-serif"><h3>Экспорт графиков</h3><pre id="log"></pre>
<script>
const log = m => document.getElementById('log').textContent += m + '\\n';
(async () => {
  const names = await (await fetch('/list')).json();
  for (const name of names) {
    const svg = await (await fetch('/svg/' + name)).text();
    const img = new Image();
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
    await img.decode();
    const c = document.createElement('canvas');
    c.width = img.width * 2; c.height = img.height * 2;
    const ctx = c.getContext('2d'); ctx.scale(2, 2); ctx.drawImage(img, 0, 0);
    const blob = await new Promise(r => c.toBlob(r, 'image/png'));
    await fetch('/save/' + name.replace('.svg', '.png'), {method: 'POST', body: blob});
    log('✓ ' + name);
  }
  log('ГОТОВО: ' + names.length);
})();
</script>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/list":
            self._send(200, json.dumps(sorted(p.name for p in FIG.glob("*.svg"))).encode(), "application/json")
        elif self.path.startswith("/svg/"):
            p = FIG / Path(self.path[5:]).name
            self._send(200, p.read_bytes(), "image/svg+xml")
        else:
            self._send(404, b"", "text/plain")

    def do_POST(self):
        if not self.path.startswith("/save/"):
            return self._send(404, b"", "text/plain")
        OUT.mkdir(exist_ok=True)
        data = self.rfile.read(int(self.headers["Content-Length"]))
        (OUT / Path(self.path[6:]).name).write_bytes(data)
        self._send(200, b"ok", "text/plain")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"http://localhost:{PORT}", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
