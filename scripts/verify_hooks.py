"""Development-only Python startup hooks for the release verifier."""

import ipaddress
import json
import logging
import os
import socket
import sys
import tempfile


def install_service_hooks():
    tempfile.tempdir = os.environ["QF_VERIFY_STORE_DIR"]
    logger = logging.getLogger("quiet_fleet.api")
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if "QF_VERIFY_BLOCKED_FILES" in os.environ:
        install_offline_guard(json.loads(os.environ["QF_VERIFY_BLOCKED_FILES"]))


def install_offline_guard(blocked_paths):
    def check_host(host):
        if host is None or host == "localhost":
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        raise PermissionError("Quiet Fleet verification denies external networking")

    def audit(event, args):
        if event in ("socket.connect", "socket.sendto", "socket.sendmsg"):
            sock, address = args[:2]
            if sock.family in (socket.AF_INET, socket.AF_INET6) and address is not None:
                check_host(address[0])
        elif event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo"):
            check_host(args[0][0] if event == "socket.getnameinfo" else args[0])
        elif event in ("open", "os.listdir", "os.scandir") and isinstance(args[0], (str, bytes)):
            path = os.path.abspath(os.fsdecode(args[0]))
            if any(path == blocked or path.startswith(blocked + os.sep) for blocked in blocked_paths):
                raise PermissionError(f"Quiet Fleet verification denies corpus access at {path}")

    sys.addaudithook(audit)
    probes = [
        lambda: socket.getaddrinfo("example.invalid", 443),
        lambda: open(blocked_paths[0], "rb").close(),
    ]
    with socket.socket() as external:
        probes.append(lambda: external.connect(("192.0.2.1", 443)))
        for probe in probes:
            try:
                probe()
            except PermissionError:
                continue
            raise RuntimeError("Offline verification guard did not deny a probe")
    print("Quiet Fleet verification denied external socket, DNS and corpus probes", flush=True)


def install_exam_observer():
    """Record the unchanged runner's measured HTTP results at the point of return."""
    filename = os.environ["QF_VERIFY_EXAM_SOURCE"]
    output = os.environ["QF_VERIFY_REQUEST_LOG"]
    monitoring = sys.monitoring
    events = monitoring.events
    tool_id = 3
    monitoring.use_tool_id(tool_id, "quiet-fleet-http-observer")

    def started(code, _offset):
        if code.co_filename == filename and code.co_qualname == "Service.request":
            monitoring.set_local_events(tool_id, code, events.PY_RETURN)
            monitoring.set_events(tool_id, 0)
        else:
            return monitoring.DISABLE

    def returned(_code, _offset, result):
        fields = sys._getframe(1).f_locals
        status, reply, seconds, error = result
        body = fields["body"]
        request = {
            "method": fields["method"], "path": fields["path"], "params": fields["params"],
            "status": status, "seconds": seconds, "error": error,
        }
        if isinstance(body, dict) and isinstance(body.get("events"), list):
            request["sent"] = len(body["events"])
            request["accepted"] = reply.get("accepted") if isinstance(reply, dict) else None
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(request) + "\n")

    monitoring.register_callback(tool_id, events.PY_START, started)
    monitoring.register_callback(tool_id, events.PY_RETURN, returned)
    monitoring.set_events(tool_id, events.PY_START)
