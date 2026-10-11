"""Vouch inbound mail receiver.

Accepts mail for ``business@<MAIL_DOMAIN>`` over SMTP (port 25 and an alternate port), stores
the raw message and attachments, parses the message into the Vouch backend's intake request
shape and forwards it over the private network with a shared-secret header. Attachments are
never executed or rendered: only read, hashed and base64-encoded.
"""

__version__ = "0.1.0"
