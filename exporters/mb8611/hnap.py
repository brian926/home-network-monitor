"""HNAP1 authentication primitives for the Motorola MB8611.

The modem uses HMAC-MD5 challenge-response. MD5 is used here because the
device's firmware requires it; it is not a security choice we control, and
the credentials never leave the LAN.
"""

import hashlib
import hmac

TIMESTAMP_MODULUS = 2000000000000
SOAP_NAMESPACE = "http://purenetworks.com/HNAP1"


def _hmac_md5(key: str, data: str) -> str:
    return hmac.new(key.encode(), data.encode(), hashlib.md5).hexdigest().upper()


def compute_private_key(public_key: str, password: str, challenge: str) -> str:
    """Derive the session private key from the login challenge."""
    return _hmac_md5(public_key + password, challenge)


def compute_login_password(private_key: str, challenge: str) -> str:
    """Derive the hashed password sent in the login request."""
    return _hmac_md5(private_key, challenge)


def compute_auth_header(private_key: str, soap_action: str, now_ms: int) -> str:
    """Build the HNAP_AUTH header value: '<digest> <timestamp>'."""
    timestamp = str(now_ms % TIMESTAMP_MODULUS)
    quoted_action = f'"{SOAP_NAMESPACE}/{soap_action}"'
    return f"{_hmac_md5(private_key, timestamp + quoted_action)} {timestamp}"
