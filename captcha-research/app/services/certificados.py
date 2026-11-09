"""Carrega certificado A1 (.pfx/.p12) direto em um SSLContext para TLS mútuo.

A chave privada nunca é gravada aberta em disco: é re-cifrada com senha
aleatória num arquivo temporário (exigência do módulo ssl) que é apagado em seguida.
"""
from __future__ import annotations

import os
import secrets
import ssl
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption, Encoding, PrivateFormat, pkcs12,
)


def carregar_pfx(pfx: Path, senha: str):
    key, cert, extras = pkcs12.load_key_and_certificates(pfx.read_bytes(), senha.encode())
    if key is None or cert is None:
        raise ValueError(f"{pfx.name}: arquivo não contém chave e certificado")
    return key, cert, extras or []


def pfx_moderno(pfx: Path, senha: str) -> tuple[bytes, str]:
    """Reempacota o .pfx (muitos A1 usam RC2/3DES, rejeitados por OpenSSL 3) em PKCS#12 AES-256,
    em memória, com senha aleatória. Retorna (bytes_pfx, senha_temporaria)."""
    from cryptography.hazmat.primitives import hashes
    key, cert, extras = carregar_pfx(pfx, senha)
    tmp = secrets.token_hex(16)
    enc = (PrivateFormat.PKCS12.encryption_builder().kdf_rounds(50000)
           .key_cert_algorithm(pkcs12.PBES.PBESv2SHA256AndAES256CBC).hmac_hash(hashes.SHA256())
           .build(tmp.encode()))
    return pkcs12.serialize_key_and_certificates(None, key, cert, extras or None, enc), tmp


def validade(pfx: Path, senha: str) -> datetime:
    _, cert, _ = carregar_pfx(pfx, senha)
    return cert.not_valid_after_utc


def criar_ssl_context(pfx: Path, senha: str, ca_bundle: str | None = None) -> ssl.SSLContext:
    key, cert, extras = carregar_pfx(pfx, senha)
    if cert.not_valid_after_utc < datetime.now(timezone.utc):
        raise ValueError(f"{pfx.name}: certificado vencido em {cert.not_valid_after_utc:%d/%m/%Y}")

    ctx = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else ssl.create_default_context()
    # Padrão NF-e é TLS 1.2; alguns servidores (ex.: SEFAZ-MT) travam no handshake se o cliente oferece TLS 1.3.
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    tmp_pass = secrets.token_hex(16)
    chain = cert.public_bytes(Encoding.PEM) + b"".join(c.public_bytes(Encoding.PEM) for c in extras)
    key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, BestAvailableEncryption(tmp_pass.encode()))

    paths = []
    try:
        for data in (chain, key_pem):
            fd, p = tempfile.mkstemp(suffix=".pem")
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            paths.append(p)
        ctx.load_cert_chain(paths[0], paths[1], password=tmp_pass)
    finally:
        for p in paths:
            os.remove(p)
    return ctx
