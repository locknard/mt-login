from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse


class MigrationDecodeError(ValueError):
    pass


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = 0
    value = 0
    while True:
        if i >= len(buf):
            raise MigrationDecodeError("Truncated varint")
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << shift
        if (b & 0x80) == 0:
            return value, i
        shift += 7
        if shift > 63:
            raise MigrationDecodeError("Varint too long")


def _read_length_delimited(buf: bytes, i: int) -> tuple[bytes, int]:
    length, i = _read_varint(buf, i)
    if length < 0 or i + length > len(buf):
        raise MigrationDecodeError("Truncated length-delimited field")
    return buf[i : i + length], i + length


def _skip_field(buf: bytes, i: int, wire_type: int) -> int:
    if wire_type == 0:
        _, i = _read_varint(buf, i)
        return i
    if wire_type == 1:
        i += 8
        if i > len(buf):
            raise MigrationDecodeError("Truncated fixed64")
        return i
    if wire_type == 2:
        _, i = _read_length_delimited(buf, i)
        return i
    if wire_type == 5:
        i += 4
        if i > len(buf):
            raise MigrationDecodeError("Truncated fixed32")
        return i
    raise MigrationDecodeError(f"Unsupported wire type: {wire_type}")


@dataclass(frozen=True)
class MigrationOtp:
    issuer: str
    name: str
    secret_base32: str
    otp_type: int  # 1=HOTP, 2=TOTP
    digits: int  # 1=SIX, 2=EIGHT, 3=SEVEN
    algorithm: int  # 1=SHA1, 2=SHA256, 3=SHA512, 4=MD5


def _to_base32(secret: bytes) -> str:
    # RFC3548 base32, uppercase, no padding
    return base64.b32encode(secret).decode("utf-8").rstrip("=")


def _decode_otp_parameters(buf: bytes) -> dict:
    out = {
        "secret": b"",
        "name": "",
        "issuer": "",
        "algorithm": 0,
        "digits": 0,
        "type": 0,
        "counter": 0,
        "unique_id": "",
    }
    i = 0
    while i < len(buf):
        key, i = _read_varint(buf, i)
        field = key >> 3
        wire = key & 0x7

        if field == 1 and wire == 2:
            out["secret"], i = _read_length_delimited(buf, i)
        elif field == 2 and wire == 2:
            raw, i = _read_length_delimited(buf, i)
            out["name"] = raw.decode("utf-8", errors="replace")
        elif field == 3 and wire == 2:
            raw, i = _read_length_delimited(buf, i)
            out["issuer"] = raw.decode("utf-8", errors="replace")
        elif field == 4 and wire == 0:
            out["algorithm"], i = _read_varint(buf, i)
        elif field == 5 and wire == 0:
            out["digits"], i = _read_varint(buf, i)
        elif field == 6 and wire == 0:
            out["type"], i = _read_varint(buf, i)
        elif field == 7 and wire == 0:
            out["counter"], i = _read_varint(buf, i)
        elif field == 8 and wire == 2:
            raw, i = _read_length_delimited(buf, i)
            out["unique_id"] = raw.decode("utf-8", errors="replace")
        else:
            i = _skip_field(buf, i, wire)
    return out


def decode_migration_payload(payload: bytes) -> list[MigrationOtp]:
    otps: list[MigrationOtp] = []
    i = 0
    while i < len(payload):
        key, i = _read_varint(payload, i)
        field = key >> 3
        wire = key & 0x7

        if field == 1 and wire == 2:
            msg, i = _read_length_delimited(payload, i)
            params = _decode_otp_parameters(msg)
            secret = params["secret"]
            otps.append(
                MigrationOtp(
                    issuer=params["issuer"] or "",
                    name=params["name"] or "",
                    secret_base32=_to_base32(secret),
                    otp_type=int(params["type"] or 0),
                    digits=int(params["digits"] or 0),
                    algorithm=int(params["algorithm"] or 0),
                )
            )
        else:
            i = _skip_field(payload, i, wire)

    return otps


def decode_migration_uri(uri: str) -> list[MigrationOtp]:
    """
    Decode Google Authenticator export URI:
    otpauth-migration://offline?data=...
    """
    uri = (uri or "").strip()
    if not uri:
        raise MigrationDecodeError("Empty migration URI")

    parsed = urlparse(uri)
    if parsed.scheme != "otpauth-migration":
        raise MigrationDecodeError("Not an otpauth-migration URI")

    qs = parse_qs(parsed.query or "")
    data_list = qs.get("data") or []
    if not data_list or not data_list[0]:
        raise MigrationDecodeError("Missing data param")

    data = unquote(data_list[0])
    # Some scanners may drop padding
    if len(data) % 4:
        data += "=" * (4 - (len(data) % 4))
    try:
        payload = base64.b64decode(data, validate=False)
    except Exception as e:
        raise MigrationDecodeError("Invalid base64 in data param") from e

    otps = decode_migration_payload(payload)
    if not otps:
        raise MigrationDecodeError("No OTP entries found in migration payload")
    return otps


def pick_best_totp(entries: list[MigrationOtp], *, username_hint: Optional[str] = None) -> MigrationOtp:
    if not entries:
        raise MigrationDecodeError("No entries to pick from")

    totps = [e for e in entries if e.otp_type in (0, 2)]  # treat 0 as unknown, allow
    if not totps:
        totps = entries

    if username_hint:
        hint = username_hint.strip().lower()
        if hint:
            for e in totps:
                if e.name.strip().lower() == hint:
                    return e
            for e in totps:
                if hint in e.name.strip().lower():
                    return e

    for e in totps:
        if "m-team" in e.issuer.lower() or "mteam" in e.issuer.lower():
            return e
    return totps[0]

