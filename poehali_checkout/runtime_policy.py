"""Render stays active; Amvera explicitly selects standby."""
import os

def is_standby():
    return os.getenv("POEHALI_RUNTIME_MODE", "active") != "active"
