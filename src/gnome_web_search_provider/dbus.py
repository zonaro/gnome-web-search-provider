#!/usr/bin/env python3
"""Minimal pure-standard-library D-Bus session service.

Implements just enough of the D-Bus wire protocol
(https://dbus.freedesktop.org/doc/dbus-specification.html) to run a GNOME
Shell ``org.gnome.Shell.SearchProvider2`` service:

* session-bus connection from ``DBUS_SESSION_BUS_ADDRESS`` with EXTERNAL auth
* ``Hello`` / ``RequestName`` registration on first use
* method-call dispatch with ``MethodReturn`` / ``Error`` replies
* marshalling for the types the search provider needs: ``s``, ``u``,
  ``as``, ``aas``, ``asu``, ``sasu`` and ``aa{sv}``

This removes the ``dasbus`` and ``PyGObject`` runtime dependencies from the
provider daemon (upstream issue #2): only the Python standard library is
used. Message bodies are little-endian.
"""

import os
import select
import socket
import struct
import threading
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Wire protocol constants
# --------------------------------------------------------------------------

MESSAGE_METHOD_CALL = 1
MESSAGE_METHOD_RETURN = 2
MESSAGE_ERROR = 3
MESSAGE_SIGNAL = 4

# Header field codes.
FIELD_PATH = 1
FIELD_INTERFACE = 2
FIELD_MEMBER = 3
FIELD_ERROR_NAME = 4
FIELD_REPLY_SERIAL = 5
FIELD_DESTINATION = 6
FIELD_SENDER = 7
FIELD_SIGNATURE = 8
FIELD_UNIX_FDS = 9

# Alignment (in bytes) of each basic type.
_BASIC_ALIGN = {
    "y": 1, "b": 4, "n": 2, "q": 2,
    "i": 4, "u": 4, "x": 8, "t": 8, "d": 8,
    "s": 4, "o": 4, "g": 1,
}


class Variant:
    """Typed value used for ``v`` signatures (e.g. ``{sv}`` dict values)."""

    __slots__ = ("signature", "value")

    def __init__(self, signature: str, value: Any):
        self.signature = signature
        self.value = value

    def unpack(self) -> Any:
        return self.value

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Variant)
            and other.signature == self.signature
            and other.value == self.value
        )

    def __repr__(self) -> str:
        return f"Variant({self.signature!r}, {self.value!r})"


class DBusError(Exception):
    """Raised to reply with a named D-Bus error."""

    def __init__(self, name: str, message: str = ""):
        super().__init__(message or name)
        self.name = name


# --------------------------------------------------------------------------
# Signature helpers
# --------------------------------------------------------------------------

def _complete_type_end(signature: str, start: int) -> int:
    """End index (exclusive) of the complete type token starting at ``start``."""
    n = len(signature)
    c = signature[start]
    if c == "v":
        return start + 1
    if c == "a":
        # An array is 'a' followed by a single complete type.
        return _complete_type_end(signature, start + 1)
    if c in "({":
        depth = 1
        i = start + 1
        while i < n and depth:
            if signature[i] in "({":
                depth += 1
            elif signature[i] in ")}":
                depth -= 1
            i += 1
        if depth:
            raise ValueError(f"unbalanced signature: {signature!r}")
        return i
    if c in "ybnqiuxtdsog":
        return start + 1
    raise ValueError(f"unsupported type code {c!r} in {signature!r}")


def split_types(signature: str) -> List[str]:
    """Split a D-Bus signature into its top-level complete type tokens."""
    types: List[str] = []
    i, n = 0, len(signature)
    while i < n:
        start = i
        i = _complete_type_end(signature, i)
        types.append(signature[start:i])
    return types


def type_align(token: str) -> int:
    """Alignment (in bytes) of a complete type token."""
    if token == "v":
        return 1  # the variant starts byte-aligned; its value aligns itself
    if token[0] == "a":
        return 4
    if token[0] in "({":
        return 8
    return _BASIC_ALIGN[token]


# --------------------------------------------------------------------------
# Marshalling
# --------------------------------------------------------------------------

def _pad(buf: bytearray, alignment: int) -> None:
    while len(buf) % alignment:
        buf.append(0)


def _pad_abs(buf: bytearray, alignment: int, base: int) -> None:
    """Pad so that ``base + len(buf)`` is aligned (D-Bus aligns to the
    message body start, not to the start of a nested array payload)."""
    while (base + len(buf)) % alignment:
        buf.append(0)


def _pack_sig(sig: str, buf: bytearray) -> None:
    raw = sig.encode("ascii")
    if len(raw) > 255:
        raise ValueError("signature too long")
    buf.append(len(raw))
    buf += raw
    buf.append(0)


def _pack_basic(token: str, value: Any, buf: bytearray) -> None:
    if token == "y":
        buf.append(int(value) & 0xFF)
    elif token == "b":
        _pad(buf, 4)
        buf += struct.pack("<I", 1 if value else 0)
    elif token in ("n", "q"):
        _pad(buf, 2)
        buf += struct.pack("<" + token, int(value))
    elif token in ("i", "u"):
        _pad(buf, 4)
        fmt = "i" if token == "i" else "I"
        buf += struct.pack("<" + fmt, int(value))
    elif token in ("x", "t", "d"):
        _pad(buf, 8)
        fmt = {"x": "q", "t": "Q", "d": "d"}[token]
        buf += struct.pack("<" + fmt, int(value) if token != "d" else float(value))
    elif token in ("s", "o"):
        _pad(buf, 4)
        raw = str(value).encode("utf-8")
        buf += struct.pack("<I", len(raw))
        buf += raw
        buf.append(0)
    elif token == "g":
        _pack_sig(str(value), buf)
    else:
        raise ValueError(f"unsupported basic type {token!r}")


def _pack_type(token: str, value: Any, buf: bytearray) -> None:
    if token == "v":
        if not isinstance(value, Variant):
            raise TypeError("variant values must be Variant instances")
        sig = value.signature
        if not sig:
            raise ValueError("empty variant signature")
        _pack_sig(sig, buf)
        _pad(buf, type_align(sig))
        _pack_type(sig, value.value, buf)
        return
    if token[0] == "a":
        sub = token[1:]
        if sub.startswith("{"):
            # a{...}: a dict whose entries are packed one at a time.
            if not isinstance(value, dict):
                if isinstance(value, (list, tuple)):
                    items = []
                    for item in value:
                        if not isinstance(item, dict) or len(item) != 1:
                            raise TypeError(f"expected single-entry dict for {token}")
                        key, inner = next(iter(item.items()))
                        items.append({key: inner})
                    value = items
                else:
                    raise TypeError(f"expected dict for {token}, got {type(value).__name__}")
            else:
                value = [{k: v} for k, v in value.items()]
        else:
            if not isinstance(value, (list, tuple)):
                raise TypeError(f"expected list for {token}, got {type(value).__name__}")
        # D-Bus aligns elements globally (to the message body start), not to the
        # array payload: pack into the buffer after a length placeholder.
        _pad(buf, 4)
        length_pos = len(buf)
        buf += b"\x00\x00\x00\x00"
        data_start = len(buf)
        for item in value:
            _pad(buf, type_align(sub))
            _pack_type(sub, item, buf)
        struct.pack_into("<I", buf, length_pos, len(buf) - data_start)
        return
    if token[0] == "(":
        subs = split_types(token[1:-1])
        if not isinstance(value, (list, tuple)) or len(value) != len(subs):
            raise TypeError(f"expected {len(subs)} values for {token}")
        _pad(buf, 8)
        for sub, item in zip(subs, value):
            _pad(buf, type_align(sub))
            _pack_type(sub, item, buf)
        return
    if token[0] == "{":
        subs = split_types(token[1:-1])
        if len(subs) != 2:
            raise ValueError(f"invalid dict entry: {token}")
        if not isinstance(value, dict) or len(value) != 1:
            raise TypeError(f"expected a single-entry dict for {token}")
        (key, item), = value.items()
        _pad(buf, 8)
        _pad(buf, type_align(subs[0]))
        _pack_type(subs[0], key, buf)
        _pad(buf, type_align(subs[1]))
        _pack_type(subs[1], item, buf)
        return
    _pack_basic(token, value, buf)


def pack_types(tokens: List[str], values: List[Any]) -> bytes:
    """Marshal ``values`` (one per token) into a message body or payload."""
    buf = bytearray()
    if len(tokens) != len(values):
        raise ValueError(f"signature has {len(tokens)} types but {len(values)} values")
    for tok, val in zip(tokens, values):
        _pack_type(tok, val, buf)
    return bytes(buf)


# --------------------------------------------------------------------------
# Unmarshalling
# --------------------------------------------------------------------------

def _align_offset(offset: int, alignment: int) -> int:
    return (offset + alignment - 1) // alignment * alignment


def _unpack_type(token: str, data: bytes, offset: int) -> Tuple[Any, int]:
    if token == "y":
        return data[offset], offset + 1
    if token == "b":
        offset = _align_offset(offset, 4)
        (val,) = struct.unpack_from("<I", data, offset)
        return bool(val), offset + 4
    if token in ("n", "q"):
        offset = _align_offset(offset, 2)
        (val,) = struct.unpack_from("<" + token, data, offset)
        return val, offset + 2
    if token in ("i", "u"):
        offset = _align_offset(offset, 4)
        fmt = "i" if token == "i" else "I"
        (val,) = struct.unpack_from("<" + fmt, data, offset)
        return val, offset + 4
    if token in ("x", "t", "d"):
        offset = _align_offset(offset, 8)
        fmt = {"x": "q", "t": "Q", "d": "d"}[token]
        (val,) = struct.unpack_from("<" + fmt, data, offset)
        return val, offset + 8
    if token in ("s", "o"):
        offset = _align_offset(offset, 4)
        (length,) = struct.unpack_from("<I", data, offset)
        offset += 4
        raw = data[offset : offset + length]
        offset += length + 1  # trailing NUL
        return raw.decode("utf-8"), offset
    if token == "g":
        (length,) = data[offset : offset + 1]
        offset += 1
        raw = data[offset : offset + length]
        offset += length + 1
        return raw.decode("ascii"), offset
    if token == "v":
        sig, offset = _unpack_type("g", data, offset)
        inner = split_types(sig)
        if len(inner) != 1:
            raise ValueError(f"variant must hold a single type, got {sig!r}")
        offset = _align_offset(offset, type_align(inner[0]))
        value, offset = _unpack_type(inner[0], data, offset)
        return Variant(sig, value), offset
    if token[0] == "a":
        sub = token[1:]
        offset = _align_offset(offset, 4)
        (length,) = struct.unpack_from("<I", data, offset)
        offset += 4
        end = offset + length
        values = []
        while offset < end:
            offset = _align_offset(offset, type_align(sub))
            value, offset = _unpack_type(sub, data, offset)
            values.append(value)
        if offset != end:
            raise ValueError("array element size mismatch")
        return values, offset
    if token[0] == "(":
        subs = split_types(token[1:-1])
        offset = _align_offset(offset, 8)
        values = []
        for sub in subs:
            offset = _align_offset(offset, type_align(sub))
            value, offset = _unpack_type(sub, data, offset)
            values.append(value)
        return values, offset
    if token[0] == "{":
        subs = split_types(token[1:-1])
        if len(subs) != 2:
            raise ValueError(f"invalid dict entry: {token}")
        offset = _align_offset(offset, 8)
        offset = _align_offset(offset, type_align(subs[0]))
        key, offset = _unpack_type(subs[0], data, offset)
        offset = _align_offset(offset, type_align(subs[1]))
        value, offset = _unpack_type(subs[1], data, offset)
        return {key: value}, offset
    raise ValueError(f"unsupported type token {token!r}")


def unpack_types(tokens: List[str], data: bytes) -> List[Any]:
    """Unmarshal ``data`` (a message body or payload) into ``tokens``."""
    offset = 0
    values = []
    for tok in tokens:
        value, offset = _unpack_type(tok, data, offset)
        values.append(value)
    return values


# --------------------------------------------------------------------------
# Message framing
# --------------------------------------------------------------------------

def build_message(
    msg_type: int,
    serial: int,
    fields: Dict[int, Variant],
    body: bytes = b"",
) -> bytes:
    """Assemble a complete D-Bus message (little-endian)."""
    # Header layout is "yyyyuua(yv)": the fixed header ends with the header
    # fields ARRAY length (bytes 12-15), and the (yv) structs start at byte
    # 16 (8-aligned, no extra framing or padding on the wire).
    header_fields = bytearray()
    for code, var in sorted(fields.items()):
        _pack_type("(yv)", (code, var), header_fields)
    buf = bytearray()
    buf.append(ord("l"))
    buf.append(msg_type & 0xFF)
    buf.append(0)  # flags
    buf.append(1)  # protocol version
    buf += struct.pack("<I", len(body))
    buf += struct.pack("<I", serial)
    buf += struct.pack("<I", len(header_fields))
    buf += header_fields
    while len(buf) % 8:
        buf.append(0)  # header is padded so the body starts 8-aligned
    buf += body
    return bytes(buf)


def unpack_message_fields(raw: bytes) -> Dict[int, Any]:
    """Decode the header fields (the raw ``(yv)`` structs, no array length)."""
    fields: Dict[int, Any] = {}
    offset = 0
    while offset < len(raw):
        (code, variant), offset = _unpack_type("(yv)", raw, offset)
        fields[int(code)] = variant.unpack()
    return fields


def parse_message(msg: bytes) -> Tuple[int, int, Dict[int, Any], bytes]:
    """Split a full wire message into (type, serial, fields, body)."""
    if len(msg) < 16:
        raise ValueError("message too short")
    if msg[0] != ord("l"):
        raise ValueError("big-endian D-Bus messages are not supported")
    (body_len, serial, fields_len) = struct.unpack_from("<III", msg, 4)
    fields = unpack_message_fields(msg[16 : 16 + fields_len])
    header_end = 16 + fields_len
    header_end += (-header_end) % 8  # header is padded so the body starts 8-aligned
    body = msg[header_end : header_end + body_len]
    return msg[1], serial, fields, body


def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    chunks = []
    remaining = n
    while remaining:
        try:
            data = sock.recv(remaining)
        except InterruptedError:
            continue
        if not data:
            return None
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)


def _read_line(sock: socket.socket) -> bytes:
    data = bytearray()
    while True:
        byte = sock.recv(1)
        if not byte:
            raise ConnectionError("bus closed during handshake")
        data += byte
        if data.endswith(b"\r\n"):
            return bytes(data[:-2])


def read_message(sock: socket.socket) -> Optional[Tuple[int, int, Dict[int, Any], bytes]]:
    """Read one framed message from the bus socket."""
    fixed = _recv_exact(sock, 16)
    if fixed is None:
        return None
    if fixed[0] != ord("l"):
        raise ValueError("big-endian D-Bus messages are not supported")
    (body_len, serial, fields_len) = struct.unpack_from("<III", fixed, 4)
    fields_raw = _recv_exact(sock, fields_len)
    if fields_raw is None:
        return None
    fields = unpack_message_fields(fields_raw)
    pad = (-(16 + fields_len)) % 8  # header is padded so the body starts 8-aligned
    if pad and _recv_exact(sock, pad) is None:
        return None
    body = _recv_exact(sock, body_len) if body_len else b""
    if body_len and body is None:
        return None
    return fixed[1], serial, fields, body


# --------------------------------------------------------------------------
# Session bus connection and authentication
# --------------------------------------------------------------------------

def _auth_handshake(sock: socket.socket) -> str:
    uid = os.geteuid()
    # EXTERNAL wants the hex encoding of the ASCII decimal uid ("1000" ->
    # "31303030"), not the hex of the number itself ("3e8").
    sock.sendall(b"\0AUTH EXTERNAL " + str(uid).encode().hex().encode() + b"\r\n")
    while True:
        line = _read_line(sock)
        if line.startswith(b"OK "):
            guid = line[3:].strip().decode("ascii")
            sock.sendall(b"BEGIN\r\n")
            # Drain any trailing data the daemon sent before BEGIN.
            sock.settimeout(0.5)
            try:
                while sock.recv(1):
                    pass
            except OSError:
                pass
            finally:
                sock.settimeout(None)
            return guid
        if line.startswith(b"REJECTED"):
            raise ConnectionError(f"bus rejected EXTERNAL auth: {line!r}")
        if line.startswith(b"DATA"):
            # EXTERNAL with empty data means "use my credentials".
            sock.sendall(b"DATA\r\n")
            continue
        if line.startswith(b"ERROR"):
            continue
        raise ConnectionError(f"unexpected auth response: {line!r}")


def _connect_bus() -> socket.socket:
    address = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    if not address:
        raise ConnectionError(
            "DBUS_SESSION_BUS_ADDRESS is not set (no session bus session?)"
        )
    last_error: Optional[BaseException] = None
    for entry in address.split(";"):
        entry = entry.strip()
        sock: Optional[socket.socket] = None
        try:
            if entry.startswith("unix:path="):
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(entry[len("unix:path=") :])
            elif entry.startswith("unix:abstract="):
                name = entry[len("unix:abstract=") :]
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect("\0" + name)
            elif entry.startswith("unix:dir="):
                directory = entry[len("unix:dir=") :]
                candidates = sorted(
                    os.path.join(directory, name)
                    for name in os.listdir(directory)
                    if os.path.isfile(os.path.join(directory, name))
                )
                if not candidates:
                    continue
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                # Same behaviour as libdbus: try the most recently used socket.
                candidates.sort(key=os.path.getmtime, reverse=True)
                sock.connect(candidates[0])
            else:
                continue
            return sock
        except OSError as exc:
            last_error = exc
            if sock is not None:
                sock.close()
            continue
    raise ConnectionError(f"could not connect to session bus: {last_error}")


class DBusService:
    """A minimal D-Bus session service that dispatches method calls."""

    def __init__(self, bus_name: str):
        self.bus_name = bus_name
        self._sock: Optional[socket.socket] = None
        self._unique_name = ""
        self._serial = 1
        self._exports: List[Tuple[str, str, Any, Dict[str, Tuple[str, Optional[str]]], str]] = []
        self._stop = threading.Event()

    # ------------------------------------------------------------ exports

    def export(
        self,
        object_path: str,
        interface: str,
        handler: Any,
        methods: Dict[str, Tuple[str, Optional[str]]],
        introspect_xml: str = "",
    ) -> None:
        """Export ``handler`` methods as D-Bus methods.

        ``methods`` maps member name -> (in_signature, out_signature); an
        out signature of ``None`` means a void reply. ``handler`` must expose
        each member as a callable attribute taking the decoded args.
        """
        self._exports.append((object_path, interface, handler, methods, introspect_xml))

    # ------------------------------------------------------------ wire i/o

    def _next_serial(self) -> int:
        self._serial += 1
        return self._serial

    def _send_message(self, msg_type: int, fields: Dict[int, Variant], body: bytes = b"") -> None:
        message = build_message(msg_type, self._next_serial(), fields, body)
        if self._sock is None:
            raise ConnectionError("not connected")
        self._sock.sendall(message)

    def _call(
        self,
        destination: str,
        path: str,
        interface: str,
        member: str,
        signature: str,
        args: List[Any],
    ) -> List[Any]:
        # Header field types are fixed by the spec: PATH is OBJECT_PATH,
        # INTERFACE/MEMBER/DESTINATION are STRING, only SIGNATURE is "g"
        # (dbus-broker validates these types and disconnects mismatches).
        fields = {
            FIELD_PATH: Variant("o", path),
            FIELD_INTERFACE: Variant("s", interface),
            FIELD_MEMBER: Variant("s", member),
            FIELD_DESTINATION: Variant("s", destination),
        }
        if signature:
            fields[FIELD_SIGNATURE] = Variant("g", signature)
        body = pack_types(split_types(signature), args) if signature else b""
        serial = self._next_serial()
        message = build_message(MESSAGE_METHOD_CALL, serial, fields, body)
        if self._sock is None:
            raise ConnectionError("not connected")
        self._sock.sendall(message)
        while True:
            reply = self._read_message()
            if reply is None:
                raise ConnectionError("bus closed while waiting for reply")
            mtype, _serial, fields2, body2 = reply
            if mtype == MESSAGE_SIGNAL:
                # The bus broadcasts signals (NameAcquired/NameOwnerChanged)
                # on the same socket; skip them until our reply arrives.
                continue
            if mtype != MESSAGE_METHOD_RETURN and mtype != MESSAGE_ERROR:
                raise RuntimeError(f"unexpected reply of type {mtype}")
            if int(fields2.get(FIELD_REPLY_SERIAL, 0)) != serial:
                continue  # reply to an earlier call; wait for ours
            if mtype == MESSAGE_ERROR:
                error_name = fields2.get(FIELD_ERROR_NAME, "org.freedesktop.DBus.Error.Failed")
                (text,) = unpack_types(["s"], body2) if body2 else ("",)
                raise RuntimeError(f"{error_name}: {text}")
            sig = fields2.get(FIELD_SIGNATURE, "")
            return unpack_types(split_types(sig), body2) if sig else []

    def _read_message(self) -> Optional[Tuple[int, int, Dict[int, Any], bytes]]:
        if self._sock is None:
            raise ConnectionError("not connected")
        return read_message(self._sock)

    def _hello(self) -> str:
        values = self._call(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "Hello",
            "",
            [],
        )
        if not values:
            raise RuntimeError("Hello returned no unique name")
        return str(values[0])

    def _request_name(self, flags: int = 0) -> int:
        values = self._call(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "RequestName",
            "su",
            [self.bus_name, flags],
        )
        return int(values[0]) if values else 0

    # ------------------------------------------------------------ lifecycle

    def connect(self) -> "DBusService":
        """Connect to the session bus, authenticate and acquire the name."""
        self._sock = _connect_bus()
        try:
            _auth_handshake(self._sock)
            self._unique_name = self._hello()
            result = self._request_name()
            # 1 = primary owner, 4 = already our own.
            if result not in (1, 4):
                self._sock.close()
                self._sock = None
                raise RuntimeError(
                    f"could not acquire name {self.bus_name} (code {result})"
                )
        except BaseException:
            if self._sock is not None:
                self._sock.close()
                self._sock = None
            raise
        return self

    def run(self) -> None:
        """Serve method calls forever (blocking)."""
        if self._sock is None:
            raise RuntimeError("not connected; call connect() first")
        try:
            while not self._stop.is_set():
                ready, _, _ = select.select([self._sock], [], [], 0.25)
                if not ready:
                    continue
                incoming = self._read_message()
                if incoming is None:
                    break  # bus went away
                mtype, call_serial, fields, body = incoming
                if mtype == MESSAGE_METHOD_CALL:
                    response = self._dispatch(fields, body, call_serial)
                    if response is not None and self._sock is not None:
                        self._sock.sendall(response)
        finally:
            try:
                if self._sock is not None:
                    self._sock.close()
            except OSError:
                pass

    # ------------------------------------------------------------- dispatch

    def _find_export(self, path: str, interface: str) -> Optional[Tuple[Any, Dict[str, Tuple[str, Optional[str]]], str]]:
        # Standard org.freedesktop.DBus.* interfaces (Introspectable, Peer,
        # Properties) are served per-path by every object, so they match by
        # path alone -- clients introspect before calling a typed method.
        if interface.startswith("org.freedesktop.DBus."):
            interface = ""
        for expath, einterface, handler, methods, xml in self._exports:
            if expath == path and (not interface or interface == einterface):
                return handler, methods, xml
        return None

    def _reply_error(self, fields: Dict[int, Any], call_serial: int, error_name: str, text: str) -> bytes:
        reply_fields = {
            FIELD_ERROR_NAME: Variant("s", error_name),
            FIELD_REPLY_SERIAL: Variant("u", call_serial),
            # The error body below is a single string, so the SIGNATURE header
            # field must say "s". A reply with a body but no signature is
            # rejected by dbus-broker ("invalid body") because a missing
            # signature implies an empty body.
            FIELD_SIGNATURE: Variant("g", "s"),
        }
        sender = fields.get(FIELD_SENDER)
        if sender:
            reply_fields[FIELD_DESTINATION] = Variant("s", sender)
        body = pack_types(["s"], [text])
        return build_message(MESSAGE_ERROR, self._next_serial(), reply_fields, body)

    def _dispatch(self, fields: Dict[int, Any], body: bytes, call_serial: int) -> Optional[bytes]:
        path = fields.get(FIELD_PATH, "")
        interface = fields.get(FIELD_INTERFACE, "")
        member = fields.get(FIELD_MEMBER, "")

        export = self._find_export(path, interface)
        handler, methods, introspect_xml = export or (None, {}, "")
        if handler is None:
            return self._reply_error(
                fields, call_serial, "org.freedesktop.DBus.Error.UnknownObject", f"unknown object path {path}"
            )
        if member == "Introspect" and introspect_xml:
            reply_body = pack_types(["s"], [introspect_xml])
            return self._method_return(fields, call_serial, "s", reply_body)
        if member not in methods:
            return self._reply_error(
                fields, call_serial, "org.freedesktop.DBus.Error.UnknownMethod", f"no method {member}"
            )
        in_sig, out_sig = methods[member]
        try:
            args = unpack_types(split_types(in_sig), body) if in_sig else []
            result = getattr(handler, member)(*args)
        except DBusError as exc:
            return self._reply_error(fields, call_serial, exc.name, str(exc))
        except Exception as exc:  # noqa: BLE001 - never crash the loop
            return self._reply_error(
                fields, call_serial, "org.freedesktop.DBus.Error.Failed", str(exc)
            )
        if out_sig is None:
            return self._method_return(fields, call_serial, "", b"")
        reply_body = pack_types(split_types(out_sig), [result])
        return self._method_return(fields, call_serial, out_sig, reply_body)

    def _method_return(self, fields: Dict[int, Any], call_serial: int, signature: str, body: bytes) -> bytes:
        reply_fields = {
            FIELD_REPLY_SERIAL: Variant("u", call_serial),
        }
        sender = fields.get(FIELD_SENDER)
        if sender:
            reply_fields[FIELD_DESTINATION] = Variant("s", sender)
        if signature:
            reply_fields[FIELD_SIGNATURE] = Variant("g", signature)
        return build_message(MESSAGE_METHOD_RETURN, self._next_serial(), reply_fields, body)


# `python -m gnome_web_search_provider.dbus` is not meant to be run directly.
if __name__ == "__main__":
    raise SystemExit("this module is a library; run 'python -m gnome_web_search_provider'")