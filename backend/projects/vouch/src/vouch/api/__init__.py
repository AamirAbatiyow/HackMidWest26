"""FastAPI surface of Vouch: the contract the existing frontend already speaks, plus intake,
vendor/sender checks, audit and the Akamai health page."""

from .app import create_app, main

__all__ = ["create_app", "main"]
