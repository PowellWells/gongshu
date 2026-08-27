"""Private-LAN phone camera provider with WebRTC live video and still capture."""

from __future__ import annotations

import asyncio
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import ipaddress
import json
from pathlib import Path
import secrets
import threading
import time
from typing import Any

from aiohttp import web
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
import cv2
import numpy as np
import qrcode

from vision2grasp.contracts import RGBFrame

from .interfaces import StillCapture
from .security import CertificateBundle, detect_lan_addresses, ensure_certificate_bundle


CAMERA_SCHEMA_VERSION = "vision2grasp.camera/v1"


@dataclass(frozen=True, slots=True)
class PhoneLANConfig:
    project_root: Path
    secret_root: Path | None = None
    capture_root: Path | None = None
    phone_asset_root: Path | None = None
    lan_address: str | None = None
    https_port: int = 8766
    bootstrap_port: int = 8767
    pairing_ttl_s: float = 300.0
    session_ttl_s: float = 1800.0
    max_capture_bytes: int = 30 * 1024 * 1024

    def __post_init__(self) -> None:
        if not 0 <= self.https_port <= 65535 or not 0 <= self.bootstrap_port <= 65535:
            raise ValueError("camera service ports must be between 0 and 65535")
        if self.pairing_ttl_s < 30.0:
            raise ValueError("pairing token lifetime must be at least 30 seconds")
        if self.session_ttl_s < self.pairing_ttl_s:
            raise ValueError("camera session lifetime must not be shorter than pairing lifetime")
        if self.max_capture_bytes < 1024 * 1024:
            raise ValueError("maximum capture size must be at least 1 MB")


class PhoneLANProvider:
    """Receive continuous phone RGB frames without invoking perception."""

    def __init__(self, config: PhoneLANConfig) -> None:
        self.config = config
        self.project_root = Path(config.project_root)
        self._secret_root = Path(config.secret_root) if config.secret_root else (
            self.project_root / "artifacts" / "camera" / "secrets"
        )
        self._capture_root = Path(config.capture_root) if config.capture_root else (
            self.project_root / "artifacts" / "camera" / "captures"
        )
        self._phone_asset_root = Path(config.phone_asset_root) if config.phone_asset_root else (
            self.project_root / "frontend" / "apps" / "gongshu" / "phone-camera"
        )
        self._lock = threading.RLock()
        self._frame_changed = threading.Condition(self._lock)
        self._frame_times: deque[float] = deque(maxlen=180)
        self._latest_frame: RGBFrame | None = None
        self._latest_jpeg: bytes | None = None
        self._frame_revision = 0
        self._latest_capture: StillCapture | None = None
        self._capture_revision = 0
        self._saved_capture_path: str | None = None
        self._next_frame_id = 0
        self._connection_status = "STOPPED"
        self._mode = "IDLE"
        self._latency_ms: float | None = None
        self._device_label = "Phone Camera"
        self._session_id: str | None = None
        self._session_created_mono = 0.0
        self._pairing_token = ""
        self._pairing_expires_mono = 0.0
        self._pairing_expires_at = ""
        self._pairing_revision = 0
        self._last_pairing_url = ""
        self._lan_addresses: tuple[str, ...] = ()
        self._lan_address = ""
        self._https_port = config.https_port
        self._bootstrap_port = config.bootstrap_port
        self._certificate: CertificateBundle | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._server_error: BaseException | None = None
        self._secure_runner: web.AppRunner | None = None
        self._bootstrap_runner: web.AppRunner | None = None
        self._peer_connections: dict[str, set[RTCPeerConnection]] = {}

    @property
    def provider_name(self) -> str:
        return "phone-lan"

    @property
    def lan_address(self) -> str:
        return self._lan_address

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            addresses = (
                (self.config.lan_address,)
                if self.config.lan_address is not None
                else detect_lan_addresses()
            )
            if not addresses:
                raise RuntimeError("无法识别可用局域网 IPv4 地址")
            self._lan_addresses = tuple(str(value) for value in addresses)
            self._lan_address = self._lan_addresses[0]
            self._certificate = ensure_certificate_bundle(
                self._secret_root,
                self._lan_addresses,
            )
            self._rotate_pairing_locked(invalidate_session=True)
            self._connection_status = "WAITING"
            self._ready.clear()
            self._server_error = None
            self._thread = threading.Thread(
                target=self._thread_main,
                name="vision2grasp-phone-lan",
                daemon=True,
            )
            self._thread.start()
        if not self._ready.wait(timeout=12.0):
            self.stop()
            raise RuntimeError("LAN Camera Service 启动超时")
        if self._server_error is not None:
            error = self._server_error
            self.stop()
            raise RuntimeError(f"LAN Camera Service 启动失败：{error}") from error

    def stop(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._async_shutdown(), loop)
            try:
                future.result(timeout=8.0)
            except (TimeoutError, RuntimeError):
                pass
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=8.0)
        with self._lock:
            self._thread = None
            self._loop = None
            self._session_id = None
            self._pairing_token = ""
            self._connection_status = "STOPPED"
            self._mode = "IDLE"
            self._latest_frame = None
            self._latest_jpeg = None
            self._latest_capture = None
            self._frame_changed.notify_all()

    def capture(self) -> RGBFrame:
        with self._lock:
            frame = self._latest_frame
            if frame is None:
                raise RuntimeError("phone camera has not delivered an RGB frame")
            return RGBFrame(
                frame_id=frame.frame_id,
                timestamp_s=frame.timestamp_s,
                camera_name=frame.camera_name,
                rgb=frame.rgb.copy(),
            )

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            service_running = self._thread is not None and self._thread.is_alive()
            if service_running:
                self._ensure_pairing_locked()
            now = time.monotonic()
            frame = self._latest_frame
            capture = self._latest_capture
            frame_age = None if frame is None else max(0.0, now - frame.timestamp_s)
            live = frame is not None and frame_age is not None and frame_age < 3.0
            effective_connection_status = (
                "LIVE"
                if live
                else "DISCONNECTED"
                if self._connection_status == "LIVE"
                else self._connection_status
            )
            return {
                "schema_version": CAMERA_SCHEMA_VERSION,
                "provider": "PhoneLANProvider",
                "service": {
                    "status": (
                        "READY" if service_running else "STOPPED"
                    ),
                    "lan_address": self._lan_address or None,
                    "https_port": self._https_port,
                    "bootstrap_port": self._bootstrap_port,
                    "setup_url": self.setup_url if self._lan_address else None,
                    "certificate_fingerprint_sha256": (
                        None
                        if self._certificate is None
                        else self._certificate.ca_fingerprint_sha256
                    ),
                },
                "pairing": {
                    "status": "PAIRED" if self._session_id else "WAITING",
                    "token_masked": "••••••••" if self._pairing_token else None,
                    "expires_at": self._pairing_expires_at or None,
                    "revision": self._pairing_revision,
                    "single_use": True,
                },
                "device": {
                    "name": self._device_label,
                    "paired": self._session_id is not None,
                },
                "connection": {
                    "status": effective_connection_status,
                    "mode": self._mode,
                    "resolution": (
                        None
                        if frame is None
                        else {"width": int(frame.rgb.shape[1]), "height": int(frame.rgb.shape[0])}
                    ),
                    "fps": round(self._received_fps_locked(now), 1),
                    "latency_ms": None if self._latency_ms is None else round(self._latency_ms, 1),
                    "frame_revision": self._frame_revision,
                    "frame_age_ms": None if frame_age is None else round(frame_age * 1000.0, 1),
                },
                "capture": {
                    "available": capture is not None,
                    "revision": self._capture_revision,
                    "captured_at": None if capture is None else capture.captured_at,
                    "content_type": None if capture is None else capture.content_type,
                    "resolution": (
                        None
                        if capture is None
                        else {
                            "width": int(capture.frame.rgb.shape[1]),
                            "height": int(capture.frame.rgb.shape[0]),
                        }
                    ),
                    "saved_path": self._saved_capture_path,
                },
                "privacy": {
                    "cloud_relay": False,
                    "cloud_storage": False,
                    "internet_upload": False,
                    "live_recording": False,
                },
            }

    @property
    def setup_url(self) -> str:
        return f"http://{self._lan_address}:{self._bootstrap_port}/setup"

    @property
    def pairing_url(self) -> str:
        with self._lock:
            self._ensure_pairing_locked()
            return self._last_pairing_url

    def refresh_pairing(self) -> None:
        with self._lock:
            self._rotate_pairing_locked(invalidate_session=True)
            self._connection_status = "WAITING"
            self._mode = "IDLE"
            self._latest_frame = None
            self._latest_jpeg = None
            self._frame_times.clear()
            self._frame_changed.notify_all()
        close_future = self._close_all_peers()
        if close_future is not None:
            try:
                close_future.result(timeout=4.0)
            except (TimeoutError, RuntimeError):
                pass

    def pairing_qr_png(self) -> bytes:
        return _qr_png(self.pairing_url)

    def setup_qr_png(self) -> bytes:
        return _qr_png(self.setup_url)

    def ca_certificate_der(self) -> bytes:
        certificate = self._certificate
        if certificate is None:
            raise RuntimeError("camera certificate is not ready")
        return certificate.ca_der_bytes()

    def latest_live_jpeg(self) -> tuple[int, bytes] | None:
        with self._lock:
            if self._latest_jpeg is None:
                return None
            return self._frame_revision, bytes(self._latest_jpeg)

    def wait_for_live_jpeg(self, revision: int, timeout: float = 2.0) -> tuple[int, bytes] | None:
        with self._frame_changed:
            self._frame_changed.wait_for(
                lambda: self._frame_revision > revision or self._connection_status == "STOPPED",
                timeout=timeout,
            )
            if self._latest_jpeg is None:
                return None
            return self._frame_revision, bytes(self._latest_jpeg)

    def latest_capture_bytes(self) -> tuple[str, bytes] | None:
        with self._lock:
            capture = self._latest_capture
            if capture is None:
                return None
            return capture.content_type, bytes(capture.original_bytes)

    def save_latest_capture(self) -> Path:
        with self._lock:
            capture = self._latest_capture
            if capture is None:
                raise RuntimeError("没有可保存的高清照片")
            extension = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
            }.get(capture.content_type, ".jpg")
            self._capture_root.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
            path = self._capture_root / f"phone-capture-{stamp}{extension}"
            path.write_bytes(capture.original_bytes)
            self._saved_capture_path = str(path)
            return path

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._async_start())
        except BaseException as error:
            self._server_error = error
            self._ready.set()
            loop.run_until_complete(self._async_shutdown())
            loop.close()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(self._async_shutdown())
            loop.close()

    async def _async_start(self) -> None:
        secure_app = web.Application(
            middlewares=[self._security_headers],
            client_max_size=self.config.max_capture_bytes,
        )
        secure_app.router.add_get("/pair/{token}", self._phone_page)
        secure_app.router.add_get("/assets/phone-camera.css", self._phone_css)
        secure_app.router.add_get("/assets/phone-camera.js", self._phone_js)
        secure_app.router.add_post("/api/pair/{token}/claim", self._claim)
        secure_app.router.add_get("/api/session/{session_id}/state", self._session_state)
        secure_app.router.add_post("/api/session/{session_id}/offer", self._offer)
        secure_app.router.add_post("/api/session/{session_id}/capture", self._capture_upload)
        secure_app.router.add_post("/api/session/{session_id}/disconnect", self._disconnect)

        bootstrap_app = web.Application(middlewares=[self._security_headers])
        bootstrap_app.router.add_get("/setup", self._setup_page)
        bootstrap_app.router.add_get("/xuanshu-camera-ca.crt", self._ca_download)

        self._secure_runner = web.AppRunner(secure_app, access_log=None)
        self._bootstrap_runner = web.AppRunner(bootstrap_app, access_log=None)
        await self._secure_runner.setup()
        await self._bootstrap_runner.setup()
        certificate = self._certificate
        if certificate is None:
            raise RuntimeError("camera certificate was not initialized")
        secure_site = web.TCPSite(
            self._secure_runner,
            host="0.0.0.0",
            port=self.config.https_port,
            ssl_context=certificate.ssl_context(),
        )
        bootstrap_site = web.TCPSite(
            self._bootstrap_runner,
            host="0.0.0.0",
            port=self.config.bootstrap_port,
        )
        await secure_site.start()
        await bootstrap_site.start()
        self._https_port = _site_port(secure_site)
        self._bootstrap_port = _site_port(bootstrap_site)
        with self._lock:
            self._update_pairing_url_locked()

    async def _async_shutdown(self) -> None:
        peers = [pc for peers in self._peer_connections.values() for pc in peers]
        self._peer_connections.clear()
        if peers:
            await asyncio.gather(*(pc.close() for pc in peers), return_exceptions=True)
        if self._secure_runner is not None:
            await self._secure_runner.cleanup()
            self._secure_runner = None
        if self._bootstrap_runner is not None:
            await self._bootstrap_runner.cleanup()
            self._bootstrap_runner = None

    @web.middleware
    async def _security_headers(self, request: web.Request, handler):  # type: ignore[no-untyped-def]
        self._require_lan_request(request)
        response = await handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        return response

    async def _phone_page(self, request: web.Request) -> web.Response:
        self._require_lan_request(request)
        token = request.match_info["token"]
        if len(token) < 20:
            raise web.HTTPNotFound()
        return web.Response(text=self._asset("index.html"), content_type="text/html")

    async def _phone_css(self, request: web.Request) -> web.Response:
        return web.Response(text=self._asset("phone-camera.css"), content_type="text/css")

    async def _phone_js(self, request: web.Request) -> web.Response:
        return web.Response(text=self._asset("phone-camera.js"), content_type="text/javascript")

    async def _setup_page(self, request: web.Request) -> web.Response:
        self._require_lan_request(request)
        certificate = self._certificate
        if certificate is None:
            raise web.HTTPServiceUnavailable()
        fingerprint = certificate.ca_fingerprint_sha256
        html = f"""<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>JINGWEI CAMERA 本地证书设置</title><style>body{{margin:0;background:#061a35;color:#e8f4ff;font:16px/1.7 system-ui,'Microsoft YaHei';}}main{{max-width:680px;margin:auto;padding:44px 24px;}}small{{color:#62d6bf;letter-spacing:.14em;}}h1{{font-size:32px;margin:10px 0;}}section{{margin-top:24px;padding:22px;border:1px solid #31557b;border-radius:16px;background:#0b2748;}}a{{display:inline-block;margin:12px 0;padding:13px 18px;border-radius:10px;background:#1e7af0;color:white;text-decoration:none;font-weight:700;}}code{{display:block;overflow-wrap:anywhere;color:#9fc9f5;font-size:11px;}}li{{margin:8px 0;}}</style></head><body><main><small>LOCAL TRUST SETUP</small><h1>JINGWEI CAMERA</h1><p>这是玄枢实验室的本地局域网证书。只需在本手机安装一次；证书私钥始终保留在电脑。</p><section><h2>首次设置</h2><ol><li>下载本地 CA 证书。</li><li>在系统设置中选择“从存储设备安装证书 / CA 证书”。</li><li>核对下方 SHA-256 指纹与电脑界面一致。</li><li>安装完成后，重新扫描电脑上的“连接手机”二维码。</li></ol><a href=\"/xuanshu-camera-ca.crt\" download>下载 XUANSHU 本地 CA</a><p>SHA-256</p><code>{fingerprint}</code></section></main></body></html>"""
        return web.Response(text=html, content_type="text/html")

    async def _ca_download(self, request: web.Request) -> web.Response:
        self._require_lan_request(request)
        return web.Response(
            body=self.ca_certificate_der(),
            content_type="application/x-x509-ca-cert",
            headers={"Content-Disposition": 'attachment; filename="xuanshu-camera-ca.crt"'},
        )

    async def _claim(self, request: web.Request) -> web.Response:
        self._require_lan_request(request)
        token = request.match_info["token"]
        try:
            session_id = self._claim_pairing(token)
        except RuntimeError as error:
            raise web.HTTPForbidden(text=str(error)) from error
        return web.json_response({"status": "ok", "session_id": session_id})

    async def _session_state(self, request: web.Request) -> web.Response:
        self._require_session(request.match_info["session_id"])
        return web.json_response(self.snapshot())

    async def _offer(self, request: web.Request) -> web.Response:
        self._require_lan_request(request)
        session_id = request.match_info["session_id"]
        self._require_session(session_id)
        document = await request.json()
        if document.get("type") != "offer" or not isinstance(document.get("sdp"), str):
            raise web.HTTPBadRequest(text="invalid WebRTC offer")
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        self._peer_connections.setdefault(session_id, set()).add(pc)
        self._set_connection(session_id, "CONNECTING")

        @pc.on("track")
        def on_track(track) -> None:  # type: ignore[no-untyped-def]
            if track.kind == "video":
                asyncio.create_task(self._consume_video(session_id, track))

        @pc.on("datachannel")
        def on_datachannel(channel) -> None:  # type: ignore[no-untyped-def]
            @channel.on("message")
            def on_message(message) -> None:  # type: ignore[no-untyped-def]
                self._handle_data_message(session_id, channel, message)

        @pc.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            state = pc.connectionState.upper()
            if state == "CONNECTED":
                self._set_connection(session_id, "CONNECTED")
            elif state in {"FAILED", "CLOSED", "DISCONNECTED"}:
                self._set_connection(session_id, "DISCONNECTED")
                if state == "FAILED":
                    await pc.close()
                if state in {"FAILED", "CLOSED"}:
                    self._peer_connections.get(session_id, set()).discard(pc)

        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=document["sdp"], type=document["type"])
        )
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return web.json_response(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
        )

    async def _capture_upload(self, request: web.Request) -> web.Response:
        self._require_lan_request(request)
        session_id = request.match_info["session_id"]
        self._require_session(session_id)
        if request.content_length is None or request.content_length <= 0:
            raise web.HTTPLengthRequired()
        if request.content_length > self.config.max_capture_bytes:
            raise web.HTTPRequestEntityTooLarge(
                max_size=self.config.max_capture_bytes,
                actual_size=request.content_length,
            )
        content_type = request.content_type.lower()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise web.HTTPUnsupportedMediaType(text="capture must be JPEG, PNG, or WebP")
        binary = await request.read()
        try:
            width, height = self._ingest_capture(session_id, binary, content_type)
        except ValueError as error:
            raise web.HTTPBadRequest(text=str(error)) from error
        return web.json_response(
            {"status": "ok", "width": width, "height": height, "bytes": len(binary)}
        )

    async def _disconnect(self, request: web.Request) -> web.Response:
        session_id = request.match_info["session_id"]
        self._require_session(session_id)
        peers = tuple(self._peer_connections.get(session_id, set()))
        await asyncio.gather(*(pc.close() for pc in peers), return_exceptions=True)
        self._peer_connections.get(session_id, set()).clear()
        self._set_connection(session_id, "PAIRED")
        return web.json_response({"status": "ok"})

    async def _consume_video(self, session_id: str, track) -> None:  # type: ignore[no-untyped-def]
        try:
            while True:
                video_frame = await track.recv()
                rgb = np.ascontiguousarray(video_frame.to_ndarray(format="rgb24"))
                self._ingest_live_frame(session_id, rgb)
        except (MediaStreamError, RuntimeError, web.HTTPException):
            self._set_connection(session_id, "PAIRED")

    def _ingest_live_frame(self, session_id: str, rgb: np.ndarray) -> None:
        now = time.monotonic()
        if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.dtype != np.uint8:
            raise ValueError("WebRTC frame must be HxWx3 uint8 RGB")
        ok, encoded = cv2.imencode(
            ".jpg",
            cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR),
            [cv2.IMWRITE_JPEG_QUALITY, 86],
        )
        if not ok:
            raise RuntimeError("failed to encode live RGB frame")
        with self._frame_changed:
            self._require_session_locked(session_id)
            frame = RGBFrame(
                frame_id=self._next_frame_id,
                timestamp_s=now,
                camera_name="phone-lan-live",
                rgb=rgb.copy(),
            )
            self._next_frame_id += 1
            self._latest_frame = frame
            self._latest_jpeg = encoded.tobytes()
            self._frame_revision += 1
            self._frame_times.append(now)
            self._connection_status = "LIVE"
            self._mode = "LIVE"
            self._frame_changed.notify_all()

    def _ingest_capture(self, session_id: str, binary: bytes, content_type: str) -> tuple[int, int]:
        bgr = cv2.imdecode(np.frombuffer(binary, dtype=np.uint8), cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError("captured image could not be decoded")
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        now = time.monotonic()
        captured_at = datetime.now().astimezone().isoformat(timespec="milliseconds")
        with self._lock:
            self._require_session_locked(session_id)
            frame = RGBFrame(
                frame_id=self._next_frame_id,
                timestamp_s=now,
                camera_name="phone-lan-capture",
                rgb=rgb,
            )
            self._next_frame_id += 1
            self._latest_capture = StillCapture(
                frame=frame,
                content_type=content_type,
                original_bytes=bytes(binary),
                captured_at=captured_at,
            )
            self._capture_revision += 1
            self._saved_capture_path = None
            self._mode = "CAPTURE"
        return int(rgb.shape[1]), int(rgb.shape[0])

    def _claim_pairing(self, token: str) -> str:
        with self._lock:
            self._ensure_pairing_locked()
            if not secrets.compare_digest(token, self._pairing_token):
                raise RuntimeError("配对令牌无效或已失效")
            session_id = secrets.token_urlsafe(32)
            self._session_id = session_id
            self._session_created_mono = time.monotonic()
            self._pairing_token = ""
            self._connection_status = "PAIRED"
            self._mode = "IDLE"
            return session_id

    def _require_session(self, session_id: str) -> None:
        with self._lock:
            self._require_session_locked(session_id)

    def _require_session_locked(self, session_id: str) -> None:
        if self._session_id is None or not secrets.compare_digest(session_id, self._session_id):
            raise web.HTTPForbidden(text="camera session is not authorized")
        if time.monotonic() - self._session_created_mono > self.config.session_ttl_s:
            self._rotate_pairing_locked(invalidate_session=True)
            self._close_all_peers()
            raise web.HTTPForbidden(text="camera session has expired")

    def _set_connection(self, session_id: str, status: str) -> None:
        with self._lock:
            if self._session_id == session_id:
                self._connection_status = status
                if status in {"PAIRED", "DISCONNECTED"}:
                    self._mode = "IDLE"

    def _handle_data_message(self, session_id: str, channel, message: Any) -> None:  # type: ignore[no-untyped-def]
        if not isinstance(message, str):
            return
        try:
            document = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            return
        if document.get("type") == "ping":
            channel.send(json.dumps({"type": "pong", "id": document.get("id")}))
            return
        if document.get("type") == "telemetry":
            latency = document.get("latency_ms")
            mode = str(document.get("mode", "LIVE")).upper()
            label = str(document.get("device", "Phone Camera"))[:80]
            with self._lock:
                if self._session_id != session_id:
                    return
                if isinstance(latency, (int, float)) and 0 <= float(latency) <= 10000:
                    self._latency_ms = float(latency)
                self._mode = mode if mode in {"LIVE", "CAPTURE", "IDLE"} else self._mode
                if label.strip():
                    self._device_label = label.strip()

    def _ensure_pairing_locked(self) -> None:
        if self._session_id is not None:
            if time.monotonic() - self._session_created_mono <= self.config.session_ttl_s:
                return
            self._rotate_pairing_locked(invalidate_session=True)
            self._connection_status = "WAITING"
            self._mode = "IDLE"
            self._close_all_peers()
        if not self._pairing_token or time.monotonic() >= self._pairing_expires_mono:
            self._rotate_pairing_locked(invalidate_session=False)

    def _rotate_pairing_locked(self, *, invalidate_session: bool) -> None:
        if invalidate_session:
            self._session_id = None
            self._session_created_mono = 0.0
        self._pairing_token = secrets.token_urlsafe(24)
        self._pairing_revision += 1
        self._update_pairing_url_locked()
        self._pairing_expires_mono = time.monotonic() + self.config.pairing_ttl_s
        expires_wall = datetime.now(timezone.utc).timestamp() + self.config.pairing_ttl_s
        self._pairing_expires_at = datetime.fromtimestamp(
            expires_wall, timezone.utc
        ).astimezone().isoformat(timespec="seconds")

    def _update_pairing_url_locked(self) -> None:
        self._last_pairing_url = (
            f"https://{self._lan_address}:{self._https_port}/pair/{self._pairing_token}"
        )

    def _received_fps_locked(self, now: float) -> float:
        while self._frame_times and now - self._frame_times[0] > 2.0:
            self._frame_times.popleft()
        if len(self._frame_times) < 2:
            return 0.0
        duration = self._frame_times[-1] - self._frame_times[0]
        return 0.0 if duration <= 0.0 else (len(self._frame_times) - 1) / duration

    def _asset(self, filename: str) -> str:
        path = self._phone_asset_root / filename
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _require_lan_request(request: web.Request) -> None:
        remote = request.remote
        if remote is None:
            raise web.HTTPForbidden(text="request origin is unavailable")
        try:
            address = ipaddress.ip_address(remote.split("%", 1)[0])
        except ValueError as error:
            raise web.HTTPForbidden(text="request origin is invalid") from error
        if not (address.is_private or address.is_loopback):
            raise web.HTTPForbidden(text="camera service accepts private LAN clients only")

    def _close_all_peers(self) -> Future[None] | None:
        loop = self._loop
        if loop is None or not loop.is_running():
            return None

        async def close() -> None:
            peers = [pc for values in self._peer_connections.values() for pc in values]
            self._peer_connections.clear()
            await asyncio.gather(*(pc.close() for pc in peers), return_exceptions=True)

        return asyncio.run_coroutine_threadsafe(close(), loop)


def _site_port(site: web.TCPSite) -> int:
    server = site._server  # noqa: SLF001 - aiohttp exposes no public bound-port accessor.
    if server is None or not server.sockets:
        raise RuntimeError("camera service did not expose a listening socket")
    return int(server.sockets[0].getsockname()[1])


def _qr_png(value: str) -> bytes:
    image = qrcode.make(value)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


__all__ = ["CAMERA_SCHEMA_VERSION", "PhoneLANConfig", "PhoneLANProvider"]
