# ============================================================
# PyMC - 协议加密与正版验证 (online-mode=true)
# ============================================================

"""
Protocol encryption and Mojang session authentication.

Login sequence when ``online-mode=true`` (identical to the vanilla server):

  C -> S  Login Start (name)
  S -> C  Encryption Request (server id "", RSA public key, verify token)
  C -> S  Encryption Response (shared secret + verify token, RSA encrypted)
          -- both directions switch to AES-128/CFB8 keyed with the secret --
  S       GET sessionserver .../hasJoined?username=..&serverId=<sha1 hash>
  S -> C  Set Compression, Login Success (real UUID + signed skin textures)

Requires the ``cryptography`` package; it is only imported when online mode
is enabled so offline servers have no extra dependency.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger("minecraft.auth")

SESSION_SERVER = "https://sessionserver.mojang.com/session/minecraft/hasJoined"


def available() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except ImportError:
        return False


class ServerKeyPair:
    """The 1024-bit RSA key pair a vanilla server generates on startup."""

    def __init__(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        self._private = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        self.public_der = self._private.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )

    def decrypt(self, data: bytes) -> bytes:
        from cryptography.hazmat.primitives.asymmetric import padding
        return self._private.decrypt(data, padding.PKCS1v15())


class StreamCipher:
    """AES-128/CFB8 in both directions, IV = shared secret."""

    def __init__(self, shared_secret: bytes):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
        try:   # cryptography >= 43 moved CFB8 to the "decrepit" namespace
            from cryptography.hazmat.decrepit.ciphers.modes import CFB8
        except ImportError:
            from cryptography.hazmat.primitives.ciphers.modes import CFB8
        cipher = Cipher(algorithms.AES(shared_secret), CFB8(shared_secret))
        self._encryptor = cipher.encryptor()
        self._decryptor = cipher.decryptor()

    def encrypt(self, data: bytes) -> bytes:
        return self._encryptor.update(data)

    def decrypt(self, data: bytes) -> bytes:
        return self._decryptor.update(data)


class DecryptingReader:
    """Wraps an asyncio StreamReader, decrypting everything read from it."""

    def __init__(self, reader, cipher: StreamCipher):
        self._reader = reader
        self._cipher = cipher

    async def readexactly(self, n: int) -> bytes:
        return self._cipher.decrypt(await self._reader.readexactly(n))


def server_id_hash(server_id: str, shared_secret: bytes, public_key_der: bytes) -> str:
    """Minecraft's signed-hex SHA-1 digest (two's complement, no zero padding)."""
    digest = hashlib.sha1()
    digest.update(server_id.encode("iso-8859-1"))
    digest.update(shared_secret)
    digest.update(public_key_der)
    number = int.from_bytes(digest.digest(), byteorder="big", signed=True)
    return format(number, "x")


def _fetch_profile(url: str) -> dict | None:
    request = urllib.request.Request(url, headers={"User-Agent": "PyMC"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                return None
            body = response.read()
    except urllib.error.HTTPError as e:
        if e.code == 204:
            return None
        raise
    if not body:
        return None
    return json.loads(body)


async def has_joined(username: str, server_hash: str, ip: str | None = None) -> dict | None:
    """
    Ask the session server whether ``username`` authenticated for this login.

    Returns the game profile ``{"id", "name", "properties": [...]}`` or None
    when the session is invalid. Raises OSError when the service is unreachable.
    """
    base = os.environ.get("PYMC_SESSION_SERVER", SESSION_SERVER)
    query = {"username": username, "serverId": server_hash}
    if ip:
        query["ip"] = ip
    url = f"{base}?{urllib.parse.urlencode(query)}"
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_profile, url)
