"""
Windows クリップボード履歴マネージャー（ローカル専用）

- バックグラウンドスレッドでWindowsのクリップボードを定期的にポーリングし、
  変化があれば履歴に追加する。
- 通常のテキストに加えて、FileMakerがフィールド定義・スクリプト・レイアウト
  オブジェクトなどをコピーした際に使う独自クリップボード形式を検出する。
  形式名を決め打ちにせず、クリップボード上の「標準テキスト以外の全形式」を
  走査し、中身に fmxmlsnippet 形式のXMLが含まれるものを自動的に見つけることで、
  どの形式名であっても(将来FileMakerが新しい形式を使っても)対応できるようにしている。
  見つかった場合は「ヘッダー部分(XML開始前の制御コード)」と「XML部分」を
  分けて保存・表示する。
- 履歴は同フォルダの history_data.json に保存し、次回起動時にも復元する。
- ブラウザからは http://127.0.0.1:8934/ にアクセスして操作する（外部には公開しない）。

このツールはローカルPC上でのみ動作し、クリップボードの内容を外部に送信することはない。
"""

import base64
import json
import struct
import threading
import time
import uuid
import xml.dom.minidom
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import win32clipboard

HOST = "127.0.0.1"
PORT = 8934
POLL_INTERVAL_SEC = 1.0
MAX_HISTORY = 200

# XML開始位置を探すためのマーカー(優先順)
XML_MARKERS = (b"<?xml", b"<fmxmlsnippet", b"<FMXMLSNIPPET")

# 中身の走査をスキップする標準テキスト形式(これらは別途テキストとして扱う)
_SKIP_STANDARD_TEXT_FORMATS = {
    win32clipboard.CF_TEXT,
    win32clipboard.CF_UNICODETEXT,
    win32clipboard.CF_OEMTEXT,
}

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_FILE = BASE_DIR / "history_data.json"

lock = threading.Lock()
history = []


def load_history():
    if DATA_FILE.exists():
        try:
            with DATA_FILE.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
    return []


def save_history():
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def find_xml_start(raw: bytes):
    """XML開始位置を返す。見つからなければ-1。"""
    for marker in XML_MARKERS:
        idx = raw.find(marker)
        if idx != -1:
            return idx
    return raw.find(b"<")


def split_header_and_xml(raw: bytes):
    """先頭の制御コード(ヘッダー)部分とXML部分を分離する。"""
    idx = find_xml_start(raw)
    if idx == -1:
        return raw, b""
    return raw[:idx], raw[idx:]


def pretty_xml(xml_bytes: bytes) -> str:
    try:
        dom = xml.dom.minidom.parseString(xml_bytes)
        pretty = dom.toprettyxml(indent="  ")
        # toprettyxmlが挿入する空行を除去して読みやすくする
        lines = [line for line in pretty.splitlines() if line.strip()]
        return "\n".join(lines)
    except Exception:
        return xml_bytes.decode("utf-8", errors="replace")


def build_fm_entry(raw: bytes, format_name: str):
    header, xml_bytes = split_header_and_xml(raw)

    header_length_value = None
    if len(header) == 4:
        header_length_value = struct.unpack("<I", header)[0]

    root_tag = None
    snippet_type = None
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_bytes)
        root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        snippet_type = root.attrib.get("type")
    except Exception:
        pass

    return {
        "id": uuid.uuid4().hex,
        "kind": "fm_xml",
        "timestamp": time.time(),
        "pinned": False,
        "format_name": format_name,
        "header_hex": header.hex(" "),
        "header_length_value": header_length_value,
        "header_b64": base64.b64encode(header).decode("ascii"),
        "xml_b64": base64.b64encode(xml_bytes).decode("ascii"),
        "xml_pretty": pretty_xml(xml_bytes),
        "root_tag": root_tag,
        "snippet_type": snippet_type,
    }


def apply_xml_edit(entry, new_xml_text: str):
    """
    ユーザーが編集したXMLテキストをエントリに反映する。
    ヘッダーが4バイトの長さプレフィックス形式の場合、編集後のバイト数に
    合わせてヘッダーも再計算する(そうしないとFileMakerへの貼り戻し時に
    XML部分の長さがずれて壊れるため)。
    """
    xml_bytes = new_xml_text.encode("utf-8")

    header = base64.b64decode(entry["header_b64"])
    if len(header) == 4:
        header = struct.pack("<I", len(xml_bytes))
        entry["header_b64"] = base64.b64encode(header).decode("ascii")
        entry["header_hex"] = header.hex(" ")
        entry["header_length_value"] = len(xml_bytes)

    entry["xml_b64"] = base64.b64encode(xml_bytes).decode("ascii")
    entry["xml_pretty"] = new_xml_text

    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_bytes)
        entry["root_tag"] = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        entry["snippet_type"] = root.attrib.get("type")
    except Exception:
        # 編集途中で一時的に不正なXMLになっていても保存自体は許可する
        pass


def build_text_entry(text: str):
    return {
        "id": uuid.uuid4().hex,
        "kind": "text",
        "timestamp": time.time(),
        "pinned": False,
        "text": text,
    }


def entry_signature(entry):
    """同一内容の重複判定に使う署名。"""
    if entry["kind"] == "fm_xml":
        return ("fm_xml", entry["xml_b64"])
    return ("text", entry["text"])


def find_fm_xml_format():
    """
    クリップボード上にある「標準テキスト以外」の全形式を走査し、
    中身にXMLらしきものが含まれる最初の形式を (format_id, format_name, raw_bytes) で返す。
    見つからなければNone。形式名を決め打ちしないことで、FileMakerが
    どんな名前のクリップボード形式を使っていても検出できるようにしている。
    """
    fmt = 0
    while True:
        fmt = win32clipboard.EnumClipboardFormats(fmt)
        if fmt == 0:
            break
        if fmt in _SKIP_STANDARD_TEXT_FORMATS:
            continue
        try:
            data = win32clipboard.GetClipboardData(fmt)
        except Exception:
            continue
        raw = bytes(data) if isinstance(data, (bytes, bytearray)) else None
        if not raw:
            continue
        if find_xml_start(raw) == -1:
            continue
        try:
            name = win32clipboard.GetClipboardFormatName(fmt)
        except Exception:
            name = f"format#{fmt}"
        return fmt, name, raw
    return None


def read_clipboard_snapshot():
    """
    今のクリップボードから1件分のエントリを作る。
    対応形式が無ければNone。
    """
    try:
        win32clipboard.OpenClipboard()
        try:
            found = find_fm_xml_format()
            if found is not None:
                _fmt, name, raw = found
                return build_fm_entry(raw, format_name=name)

            if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
                text = win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                if text and text.strip():
                    return build_text_entry(text)
            return None
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        return None


def write_clipboard_entry(entry):
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        if entry["kind"] == "fm_xml":
            fm_fmt_id = win32clipboard.RegisterClipboardFormat(entry["format_name"])
            raw = base64.b64decode(entry["header_b64"]) + base64.b64decode(entry["xml_b64"])
            win32clipboard.SetClipboardData(fm_fmt_id, raw)
        else:
            win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, entry["text"])
    finally:
        win32clipboard.CloseClipboard()


def poll_clipboard_loop():
    last_signature = None
    while True:
        entry = read_clipboard_snapshot()
        if entry is not None:
            sig = entry_signature(entry)
            if sig != last_signature:
                last_signature = sig
                with lock:
                    global history
                    history = [h for h in history if entry_signature(h) != sig]
                    history.insert(0, entry)
                    pinned = [h for h in history if h["pinned"]]
                    unpinned = [h for h in history if not h["pinned"]]
                    if len(pinned) + len(unpinned) > MAX_HISTORY:
                        unpinned = unpinned[: max(0, MAX_HISTORY - len(pinned))]
                    history = sorted(pinned + unpinned, key=lambda h: h["timestamp"], reverse=True)
                    save_history()
        time.sleep(POLL_INTERVAL_SEC)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _serve_static(self, path):
        if path == "/":
            path = "/index.html"
        file_path = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR not in file_path.parents and file_path != STATIC_DIR:
            self.send_error(403)
            return
        if not file_path.is_file():
            self.send_error(404)
            return
        content_type = "text/html; charset=utf-8"
        if file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif file_path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/history":
            with lock:
                self._send_json({"items": history})
            return
        self._serve_static(path)

    def do_POST(self):
        global history
        path = urlparse(self.path).path
        body = self._read_json_body()

        if path == "/api/copy":
            item_id = body.get("id")
            with lock:
                target = next((h for h in history if h["id"] == item_id), None)
            if target:
                write_clipboard_entry(target)
                self._send_json({"ok": True})
            else:
                self._send_json({"ok": False, "error": "not_found"}, status=404)
            return

        if path == "/api/update-xml":
            item_id = body.get("id")
            new_xml_text = body.get("xml_text", "")
            with lock:
                target = next((h for h in history if h["id"] == item_id), None)
                if target and target.get("kind") == "fm_xml":
                    apply_xml_edit(target, new_xml_text)
                    save_history()
                    self._send_json({"ok": True, "item": target})
                else:
                    self._send_json({"ok": False, "error": "not_found"}, status=404)
            return

        if path == "/api/delete":
            item_id = body.get("id")
            with lock:
                history = [h for h in history if h["id"] != item_id]
                save_history()
            self._send_json({"ok": True})
            return

        if path == "/api/clear":
            with lock:
                history = [h for h in history if h["pinned"]]
                save_history()
            self._send_json({"ok": True})
            return

        if path == "/api/pin":
            item_id = body.get("id")
            with lock:
                for h in history:
                    if h["id"] == item_id:
                        h["pinned"] = not h["pinned"]
                save_history()
            self._send_json({"ok": True})
            return

        self.send_error(404)


def main():
    global history
    history = load_history()

    poller = threading.Thread(target=poll_clipboard_loop, daemon=True)
    poller.start()

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}/"
    print(f"クリップボード履歴マネージャーを起動しました: {url}")
    print("終了するには Ctrl+C を押してください。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
