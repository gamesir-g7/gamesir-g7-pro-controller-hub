#!/usr/bin/env python3
"""
gamesir-connect-codec - decode & encode GameSir Connect profile share codes.

GameSir Connect exports a controller profile as a clipboard "share code":

    GAMESIR:<base64...>

This library/CLI decodes those codes into readable JSON and re-encodes JSON
back into a valid share code, so you can back up, inspect, diff, edit, and
share your own controller profiles outside the app.

Format (reverse-engineered from the desktop app):

    GAMESIR: + base64( AES-256-CBC( base64( gzip( JSON ) ) ) )

    key/iv : OpenSSL EVP_BytesToKey(MD5, password, no salt) -> key(32) + iv(16)
             (mirrors Node's legacy crypto.createCipher('aes-256-cbc', password))
    password: "SZHJC"  -- hardcoded in the app and shared across every model
             GameSir Connect supports, so this works for all of them.

The decoded JSON is a packet:

    {"v":1, "appVer":"...", "productType":"...", "ts":<ms>, "diff":{...}}

where `diff` holds only the settings that differ from the controller's default
profile (button maps, stick dead zones / curves, triggers, etc.).

Not affiliated with or endorsed by GameSir. Provided for interoperability and
for backing up your own data. The format may change in future app versions.

Requires: cryptography   (pip install -r requirements.txt)
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import os
import sys
import zlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DEFAULT_PREFIX = "GAMESIR:"
DEFAULT_PASSWORD = "SZHJC"


def _evp_bytes_to_key(password: str, key_len: int = 32, iv_len: int = 16):
    """OpenSSL EVP_BytesToKey: MD5, no salt, 1 iteration (matches createCipher)."""
    pw = password.encode()
    out = b""
    block = b""
    while len(out) < key_len + iv_len:
        block = hashlib.md5(block + pw).digest()
        out += block
    return out[:key_len], out[key_len:key_len + iv_len]


def _pkcs7_pad(data: bytes) -> bytes:
    n = 16 - (len(data) % 16)
    return data + bytes([n]) * n


def _pkcs7_unpad(data: bytes) -> bytes:
    n = data[-1]
    if not 1 <= n <= 16 or data[-n:] != bytes([n]) * n:
        raise ValueError("bad PKCS#7 padding (wrong password or corrupt code?)")
    return data[:-n]


def _b64d(s: str) -> bytes:
    return base64.b64decode(s + "=" * ((4 - len(s) % 4) % 4))


def decode(code: str, password: str = DEFAULT_PASSWORD,
           prefix: str = DEFAULT_PREFIX) -> dict:
    """Decode a ``GAMESIR:`` share code into the profile packet dict."""
    s = code.strip()
    if prefix and s.startswith(prefix):
        s = s[len(prefix):]
    s = s.strip()
    key, iv = _evp_bytes_to_key(password)
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    inner_b64 = _pkcs7_unpad(dec.update(_b64d(s)) + dec.finalize()).decode("utf-8")
    payload = zlib.decompress(_b64d(inner_b64), 16 + zlib.MAX_WBITS)
    return json.loads(payload.decode("utf-8"))


def encode(packet: dict, password: str = DEFAULT_PASSWORD,
           prefix: str = DEFAULT_PREFIX) -> str:
    """Encode a profile packet dict into a ``GAMESIR:`` share code."""
    raw = json.dumps(packet, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    inner_b64 = base64.b64encode(gzip.compress(raw, mtime=0))
    key, iv = _evp_bytes_to_key(password)
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = enc.update(_pkcs7_pad(inner_b64)) + enc.finalize()
    return prefix + base64.b64encode(ct).decode("ascii")


# --- importability ---------------------------------------------------------
# GameSir's app has an export/import asymmetry: its exporter (buildDiff) writes
# any field present in your live profile, but its importer (validateDiffStrict)
# REJECTS any field not in a fixed base template -- so codes carrying e.g. the
# G7 Pro's upper paddles (FL2/FR2) or antiJitter import as "invalid profile
# contents". base_model.json (bundled) is that template; the helpers below strip
# a diff to only what the importer accepts. See KNOWN_ISSUES.md.

_BASE_MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "base_model.json")


def load_base_model(path: str = _BASE_MODEL_PATH) -> dict:
    """Load the bundled default-profile template the importer validates against."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _jstype(v):
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    return "object"


def _filter_to_template(template, diff, path=""):
    """Keep only diff keys the importer accepts; return (kept, removed_paths).

    Mirrors the app's validateDiffStrict: a key survives only if it exists in the
    template with a compatible type (objects recurse, arrays stay, primitives must
    match JS typeof). Whatever is dropped is exactly what the importer rejects.
    """
    kept, removed = {}, []
    if not isinstance(diff, dict):
        return diff, removed
    for k, v in diff.items():
        here = path + k
        if not (isinstance(template, dict) and k in template):
            removed.append(here)
            continue
        t = template[k]
        if isinstance(t, dict):
            if isinstance(v, dict):
                sub, rem = _filter_to_template(t, v, here + ".")
                removed += rem
                if sub:
                    kept[k] = sub
            else:
                removed.append(here)
        elif isinstance(t, list):
            if isinstance(v, list):
                kept[k] = v
            else:
                removed.append(here)
        elif isinstance(v, (dict, list)):
            removed.append(here)
        elif t is None or v is None or _jstype(t) == _jstype(v):
            kept[k] = v
        else:
            removed.append(here)
    return kept, removed


def make_importable(packet: dict, base_model: dict = None):
    """Strip a packet's diff to only fields GameSir's importer accepts.

    Returns ``(new_packet, removed_paths)``. The removed fields are the ones you
    re-add by hand in the app after importing (e.g. FL2/FR2 paddle maps).
    """
    if base_model is None:
        base_model = load_base_model()
    out = dict(packet)
    diff = packet.get("diff", packet)
    filtered, removed = _filter_to_template(base_model, diff)
    if "diff" in packet:
        out["diff"] = filtered
    else:
        out = filtered
    return out, removed


def _main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="gamesir_codec",
        description="Decode/encode GameSir Connect profile share codes.")
    p.add_argument("--password", default=DEFAULT_PASSWORD,
                   help="override the share-code password (default: SZHJC)")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("decode", help="GAMESIR: code -> JSON")
    d.add_argument("code", nargs="?", help="the GAMESIR:... code (or -i / stdin)")
    d.add_argument("-i", "--input", help="read the code from a file")
    d.add_argument("-o", "--output", help="write JSON here (default: stdout)")

    e = sub.add_parser("encode", help="JSON -> GAMESIR: code")
    e.add_argument("json", nargs="?", help="path to a JSON file (or stdin)")
    e.add_argument("-o", "--output", help="write the code here (default: stdout)")
    e.add_argument("--importable", action="store_true",
                   help="strip fields GameSir's importer rejects (e.g. FL2/FR2 "
                        "paddles, antiJitter); removed fields are listed on stderr")

    a = p.parse_args(argv)
    try:
        if a.cmd == "decode":
            code = a.code or (open(a.input, encoding="utf-8").read()
                              if a.input else sys.stdin.read())
            text = json.dumps(decode(code.strip(), a.password), indent=2,
                              ensure_ascii=False)
        else:
            raw = open(a.json, encoding="utf-8").read() if a.json else sys.stdin.read()
            packet = json.loads(raw)
            if a.importable:
                packet, removed = make_importable(packet)
                if removed:
                    print("note: stripped %d field(s) the app's importer would "
                          "reject (re-add them in-app):" % len(removed), file=sys.stderr)
                    for r in removed:
                        print("  - " + r, file=sys.stderr)
            text = encode(packet, a.password)
    except Exception as ex:  # noqa: BLE001 - surface a clean message to the CLI
        print(f"error: {ex}", file=sys.stderr)
        return 1

    if a.output:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
