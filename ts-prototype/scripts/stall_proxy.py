"""Fault-injecting HTTP proxy for the PUBLIC read endpoint (test tooling). It ACCEPTS a request, reads it fully, and then WITHHOLDS the response
(the connection stays open, nothing is sent) for the resource class currently selected; all other requests are forwarded unchanged.

modes: none | checkpoint (/checkpoint) | tile (/tile/<level>/..., not entries) | entries (/tile/entries/...)
"""
import socket, socketserver, threading, time

class StallProxy:
    def __init__(self, upstream_port, port=0):
        self.upstream = upstream_port
        self.mode = "none"
        self.release_ev = threading.Event()
        self.stalled = []          # (monotonic time, path) of every withheld request
        self.forwarded = 0
        outer = self
        class H(socketserver.BaseRequestHandler):
            def handle(self):
                s = self.request; s.settimeout(30); buf = b""
                try:
                    while b"\r\n\r\n" not in buf:
                        c = s.recv(65536)
                        if not c: return
                        buf += c
                except OSError: return
                path = buf.split(b" ", 2)[1].decode("latin1")
                cls = "checkpoint" if path == "/checkpoint" else "entries" if path.startswith("/tile/entries/") else "tile" if path.startswith("/tile/") else "other"
                if outer.mode == cls:
                    outer.stalled.append((time.monotonic(), path))
                    outer.release_ev.wait()      # hold the request, send nothing; on release the connection is simply closed
                    return
                try:
                    u = socket.create_connection(("127.0.0.1", outer.upstream), timeout=10)
                    req = buf.replace(b"\r\n\r\n", b"\r\nConnection: close\r\n\r\n", 1)
                    u.sendall(req)
                    while True:
                        d = u.recv(65536)
                        if not d: break
                        s.sendall(d)
                    u.close(); outer.forwarded += 1
                except OSError: pass
        class S(socketserver.ThreadingMixIn, socketserver.TCPServer):
            allow_reuse_address = True; daemon_threads = True
        self.srv = S(("127.0.0.1", port), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
    def stall(self, mode):
        self.release_ev = threading.Event(); self.stalled = []; self.mode = mode
    def release(self):
        self.mode = "none"; self.release_ev.set()
    def close(self):
        self.release(); self.srv.shutdown(); self.srv.server_close()
