from __future__ import annotations

import asyncio
from fractions import Fraction
import io
import json
from pathlib import Path
import tempfile
import time
import unittest

from aiohttp import ClientSession, TCPConnector
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame
from cryptography import x509
from cryptography.x509.oid import ExtensionOID
import cv2
import numpy as np

from vision2grasp.camera import PhoneLANConfig, PhoneLANProvider
from vision2grasp.camera.security import ensure_certificate_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHONE_ASSETS = PROJECT_ROOT / "frontend" / "apps" / "gongshu" / "phone-camera"


class _ContinuousRGBTrack(VideoStreamTrack):
    """Deterministic live source used to prove the receiver consumes many frames."""

    def __init__(self) -> None:
        super().__init__()
        self.frames_sent = 0

    async def recv(self) -> VideoFrame:
        await asyncio.sleep(1.0 / 24.0)
        self.frames_sent += 1
        rgb = np.zeros((96, 128, 3), dtype=np.uint8)
        rgb[:, :, 0] = self.frames_sent % 255
        rgb[:, :, 1] = 70
        rgb[:, :, 2] = 180
        frame = VideoFrame.from_ndarray(rgb, format="rgb24")
        frame.pts = self.frames_sent
        frame.time_base = Fraction(1, 24)
        return frame


class CertificateTests(unittest.TestCase):
    def test_local_ca_persists_and_server_certificate_covers_lan_ip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first = ensure_certificate_bundle(root, ("192.168.50.12",))
            second = ensure_certificate_bundle(root, ("192.168.50.12",))

            self.assertEqual(first.ca_fingerprint_sha256, second.ca_fingerprint_sha256)
            self.assertNotIn("BEGIN PRIVATE KEY", first.ca_der_bytes().decode("latin1"))
            server = x509.load_pem_x509_certificate(first.server_certificate_path.read_bytes())
            san = server.extensions.get_extension_for_oid(
                ExtensionOID.SUBJECT_ALTERNATIVE_NAME
            ).value
            self.assertIn("192.168.50.12", [str(value) for value in san.get_values_for_type(x509.IPAddress)])


class PhoneLANProviderIntegrationTests(unittest.TestCase):
    def test_continuous_webrtc_live_and_high_resolution_capture(self) -> None:
        asyncio.run(self._exercise_provider())

    async def _exercise_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            runtime_root = Path(temporary_directory)
            provider = PhoneLANProvider(
                PhoneLANConfig(
                    project_root=PROJECT_ROOT,
                    secret_root=runtime_root / "secrets",
                    capture_root=runtime_root / "captures",
                    phone_asset_root=PHONE_ASSETS,
                    lan_address="127.0.0.1",
                    https_port=0,
                    bootstrap_port=0,
                    pairing_ttl_s=30.0,
                    session_ttl_s=90.0,
                )
            )
            provider.start()
            peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
            track = _ContinuousRGBTrack()
            try:
                state = provider.snapshot()
                self.assertEqual(state["service"]["status"], "READY")
                self.assertFalse(state["privacy"]["cloud_relay"])
                self.assertFalse(state["privacy"]["internet_upload"])
                first_pairing_revision = state["pairing"]["revision"]

                connector = TCPConnector(ssl=False)
                async with ClientSession(connector=connector) as session:
                    pairing_url = provider.pairing_url
                    token = pairing_url.rsplit("/", 1)[-1]
                    secure_base = pairing_url.split("/pair/", 1)[0]
                    phone_page = await session.get(pairing_url)
                    self.assertEqual(phone_page.status, 200)
                    self.assertIn("JINGWEI CAMERA", await phone_page.text())
                    setup_page = await session.get(provider.setup_url)
                    self.assertEqual(setup_page.status, 200)
                    self.assertIn("LOCAL TRUST SETUP", await setup_page.text())
                    claim_response = await session.post(f"{secure_base}/api/pair/{token}/claim")
                    self.assertEqual(claim_response.status, 200)
                    session_id = (await claim_response.json())["session_id"]

                    reused = await session.post(f"{secure_base}/api/pair/{token}/claim")
                    self.assertEqual(reused.status, 403)
                    await reused.read()

                    peer.addTrack(track)
                    channel = peer.createDataChannel("xuanshu-telemetry")
                    pong_received = asyncio.Event()

                    @channel.on("open")
                    def on_open() -> None:
                        channel.send('{"type":"ping","id":"integration-ping"}')
                        channel.send(
                            '{"type":"telemetry","latency_ms":18.5,'
                            '"mode":"LIVE","device":"Integration Camera"}'
                        )

                    @channel.on("message")
                    def on_message(message: str) -> None:
                        document = json.loads(message)
                        if document.get("type") == "pong" and document.get("id") == "integration-ping":
                            pong_received.set()

                    offer = await peer.createOffer()
                    await peer.setLocalDescription(offer)
                    offer_response = await session.post(
                        f"{secure_base}/api/session/{session_id}/offer",
                        json={
                            "sdp": peer.localDescription.sdp,
                            "type": peer.localDescription.type,
                        },
                    )
                    self.assertEqual(offer_response.status, 200)
                    answer = await offer_response.json()
                    await peer.setRemoteDescription(
                        RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
                    )

                    deadline = time.monotonic() + 10.0
                    live_state = provider.snapshot()
                    while (
                        live_state["connection"]["frame_revision"] < 10
                        and time.monotonic() < deadline
                    ):
                        await asyncio.sleep(0.1)
                        live_state = provider.snapshot()

                    self.assertGreaterEqual(live_state["connection"]["frame_revision"], 10)
                    self.assertEqual(live_state["connection"]["status"], "LIVE")
                    self.assertEqual(
                        live_state["connection"]["resolution"],
                        {"width": 128, "height": 96},
                    )
                    self.assertGreater(live_state["connection"]["fps"], 5.0)
                    self.assertGreater(track.frames_sent, 10)
                    await asyncio.wait_for(pong_received.wait(), timeout=3.0)
                    self.assertEqual(provider.snapshot()["connection"]["latency_ms"], 18.5)
                    live_frame = provider.capture()
                    self.assertEqual(live_frame.rgb.shape, (96, 128, 3))
                    self.assertGreater(live_frame.frame_id, 1)
                    current_jpeg = provider.latest_live_jpeg()
                    self.assertIsNotNone(current_jpeg)
                    next_jpeg = await asyncio.to_thread(
                        provider.wait_for_live_jpeg, current_jpeg[0], 2.0
                    )
                    self.assertIsNotNone(next_jpeg)
                    self.assertGreater(next_jpeg[0], current_jpeg[0])

                    high_resolution_bgr = np.random.default_rng(7).integers(
                        0, 256, size=(1800, 2400, 3), dtype=np.uint8
                    )
                    encoded_ok, encoded = cv2.imencode(
                        ".jpg", high_resolution_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95]
                    )
                    self.assertTrue(encoded_ok)
                    original = encoded.tobytes()
                    self.assertGreater(len(original), 1024 * 1024)
                    capture_response = await session.post(
                        f"{secure_base}/api/session/{session_id}/capture",
                        data=io.BytesIO(original),
                        headers={"Content-Type": "image/jpeg"},
                    )
                    self.assertEqual(capture_response.status, 200)
                    capture_result = await capture_response.json()
                    self.assertEqual(
                        (capture_result["width"], capture_result["height"]),
                        (2400, 1800),
                    )
                    self.assertEqual(provider.latest_capture_bytes(), ("image/jpeg", original))
                    self.assertFalse((runtime_root / "captures").exists())

                    saved = provider.save_latest_capture()
                    self.assertEqual(saved.parent, runtime_root / "captures")
                    self.assertEqual(saved.read_bytes(), original)

                    provider.refresh_pairing()
                    refreshed_state = provider.snapshot()
                    self.assertFalse(refreshed_state["device"]["paired"])
                    self.assertGreater(
                        refreshed_state["pairing"]["revision"], first_pairing_revision
                    )
                    self.assertNotEqual(provider.pairing_url.rsplit("/", 1)[-1], token)
                    expired_session = await session.get(
                        f"{secure_base}/api/session/{session_id}/state"
                    )
                    self.assertEqual(expired_session.status, 403)
                    await expired_session.read()
            finally:
                await peer.close()
                provider.stop()

            self.assertEqual(provider.snapshot()["service"]["status"], "STOPPED")


if __name__ == "__main__":
    unittest.main()
