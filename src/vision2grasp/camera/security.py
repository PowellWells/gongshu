"""LAN discovery and local certificate lifecycle for the phone camera service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
from pathlib import Path
import socket
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


@dataclass(frozen=True, slots=True)
class CertificateBundle:
    ca_certificate_path: Path
    ca_private_key_path: Path
    server_certificate_path: Path
    server_private_key_path: Path
    ca_fingerprint_sha256: str

    def ssl_context(self) -> ssl.SSLContext:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(
            certfile=str(self.server_certificate_path),
            keyfile=str(self.server_private_key_path),
        )
        return context

    def ca_der_bytes(self) -> bytes:
        certificate = x509.load_pem_x509_certificate(self.ca_certificate_path.read_bytes())
        return certificate.public_bytes(serialization.Encoding.DER)


def detect_lan_addresses() -> tuple[str, ...]:
    """Return usable private IPv4 addresses with the active route first."""

    candidates: list[str] = []
    route_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        route_socket.connect(("192.0.2.1", 9))
        candidates.append(str(route_socket.getsockname()[0]))
    except OSError:
        pass
    finally:
        route_socket.close()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(str(info[4][0]))
    except OSError:
        pass

    usable: list[str] = []
    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.version != 4 or address.is_loopback or not address.is_private:
            continue
        if candidate not in usable:
            usable.append(candidate)
    return tuple(usable)


def ensure_certificate_bundle(secret_root: Path, lan_addresses: tuple[str, ...]) -> CertificateBundle:
    """Create a persistent local CA and a replaceable server certificate."""

    if not lan_addresses:
        raise RuntimeError("no private LAN IPv4 address is available for phone pairing")
    root = Path(secret_root)
    root.mkdir(parents=True, exist_ok=True)
    ca_key_path = root / "camera-local-ca-key.pem"
    ca_cert_path = root / "camera-local-ca.pem"
    server_key_path = root / "camera-server-key.pem"
    server_cert_path = root / "camera-server.pem"

    if ca_key_path.is_file() and ca_cert_path.is_file():
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        ca_cert = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    else:
        ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "XUANSHU LAB"),
                x509.NameAttribute(NameOID.COMMON_NAME, "XUANSHU Local Camera CA"),
            ]
        )
        now = datetime.now(timezone.utc)
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .sign(ca_key, hashes.SHA256())
        )
        _write_private_key(ca_key_path, ca_key)
        ca_cert_path.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    server_subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "XUANSHU LAB"),
            x509.NameAttribute(NameOID.COMMON_NAME, lan_addresses[0]),
        ]
    )
    san_entries: list[x509.GeneralName] = [
        x509.IPAddress(ipaddress.ip_address(address)) for address in lan_addresses
    ]
    san_entries.extend(
        [
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            x509.DNSName("localhost"),
            x509.DNSName(socket.gethostname()),
        ]
    )
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_subject)
        .issuer_name(ca_cert.subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=45))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )
    _write_private_key(server_key_path, server_key)
    server_cert_path.write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))

    fingerprint = hashlib.sha256(ca_cert.public_bytes(serialization.Encoding.DER)).hexdigest().upper()
    formatted = ":".join(fingerprint[index : index + 2] for index in range(0, len(fingerprint), 2))
    return CertificateBundle(
        ca_certificate_path=ca_cert_path,
        ca_private_key_path=ca_key_path,
        server_certificate_path=server_cert_path,
        server_private_key_path=server_key_path,
        ca_fingerprint_sha256=formatted,
    )


def _write_private_key(path: Path, key) -> None:  # type: ignore[no-untyped-def]
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass


__all__ = ["CertificateBundle", "detect_lan_addresses", "ensure_certificate_bundle"]
