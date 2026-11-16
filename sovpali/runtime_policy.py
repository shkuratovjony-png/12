"""Deployment policy. Existing Render entrypoint keeps its active behavior."""
import os


def is_standby():
    return os.getenv("SOVPALI_RUNTIME_MODE", "active") != "active"
