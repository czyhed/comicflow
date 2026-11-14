"""Test-only TCP forwarding to three fixed isolated services; no arbitrary destination."""
import select
import socket
import socketserver
import threading


class Proxy(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(self.server.destination, timeout=15) as upstream:
            upstream.settimeout(None)
            sockets = [self.request, upstream]
            while True:
                ready, _, _ = select.select(sockets, [], [], 60)
                if not ready:
                    return
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.request else self.request).sendall(data)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


for port, destination in [(15432, ('postgres', 5432)), (19000, ('minio', 9000)),
                           (16379, ('redis', 6379))]:
    server = Server(('0.0.0.0', port), Proxy)
    server.destination = destination
    threading.Thread(target=server.serve_forever, daemon=True).start()
threading.Event().wait()
