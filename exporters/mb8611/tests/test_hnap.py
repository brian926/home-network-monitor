import re

from exporters.mb8611.hnap import (
    compute_auth_header,
    compute_login_password,
    compute_private_key,
)

HEX32 = re.compile(r"^[0-9A-F]{32}$")


def test_private_key_is_uppercase_hex_digest():
    key = compute_private_key("PUBKEY", "hunter2", "CHALLENGE")
    assert HEX32.match(key)


def test_private_key_is_deterministic():
    a = compute_private_key("PUBKEY", "hunter2", "CHALLENGE")
    b = compute_private_key("PUBKEY", "hunter2", "CHALLENGE")
    assert a == b


def test_private_key_changes_with_password():
    a = compute_private_key("PUBKEY", "hunter2", "CHALLENGE")
    b = compute_private_key("PUBKEY", "hunter3", "CHALLENGE")
    assert a != b


def test_private_key_changes_with_challenge():
    a = compute_private_key("PUBKEY", "hunter2", "CHALLENGE_A")
    b = compute_private_key("PUBKEY", "hunter2", "CHALLENGE_B")
    assert a != b


def test_login_password_is_uppercase_hex_digest():
    assert HEX32.match(compute_login_password("PRIVKEY", "CHALLENGE"))


def test_auth_header_is_digest_space_timestamp():
    header = compute_auth_header("PRIVKEY", "GetMultipleHNAPs", 1735689600000)
    digest, timestamp = header.split(" ")
    assert HEX32.match(digest)
    assert timestamp == "1735689600000"


def test_auth_header_timestamp_wraps_at_modulus():
    header = compute_auth_header("PRIVKEY", "GetMultipleHNAPs", 2000000000001)
    assert header.split(" ")[1] == "1"
