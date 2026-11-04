from __future__ import annotations

import os
import tempfile
from pathlib import Path

import jwt
from cryptography.fernet import Fernet
from jwt import PyJWKClient

from backup_export import create_backup_file

OIDC_ISSUER = "https://token.actions.githubusercontent.com"
OIDC_JWKS = "https://token.actions.githubusercontent.com/.well-known/jwks"
OIDC_AUDIENCE = "sovpali-backup"
EXPECTED_REPOSITORY = "shkuratovjony-png/12"
EXPECTED_WORKFLOW_SUFFIX = "/.github/workflows/sovpali-backup.yml@refs/heads/main"


def verify_github_oidc(token: str) -> dict:
    if not token:
        raise ValueError("missing token")
    jwk_client = PyJWKClient(OIDC_JWKS, cache_keys=True)
    signing_key = jwk_client.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        audience=OIDC_AUDIENCE,
        issuer=OIDC_ISSUER,
        options={"require": ["exp", "iat", "iss", "aud"]},
    )
    if claims.get("repository") != EXPECTED_REPOSITORY:
        raise ValueError("unexpected repository")
    workflow_ref = claims.get("workflow_ref", "")
    if not workflow_ref.endswith(EXPECTED_WORKFLOW_SUFFIX):
        raise ValueError("unexpected workflow")
    return claims


def create_encrypted_backup_file():
    key = os.getenv("BACKUP_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("BACKUP_ENCRYPTION_KEY is not configured")

    source_path, source_name = create_backup_file()
    encrypted = tempfile.NamedTemporaryFile(
        prefix="sovpali-backup-", suffix=".json.gz.fernet", delete=False
    )
    encrypted_path = encrypted.name
    encrypted.close()

    try:
        plaintext = Path(source_path).read_bytes()
        ciphertext = Fernet(key.encode("ascii")).encrypt(plaintext)
        Path(encrypted_path).write_bytes(ciphertext)
        return encrypted_path, source_name + ".fernet"
    finally:
        try:
            os.unlink(source_path)
        except OSError:
            pass
