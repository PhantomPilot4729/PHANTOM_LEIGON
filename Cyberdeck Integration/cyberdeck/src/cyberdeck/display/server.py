import socket, threading, json, time

class DisplayServer:
    def __init__(self, host="0.0.0.0", port=9999):
        self.host = host
        self.port = port
        self.clients = []
        self.lock = threading.Lock()
        self._start_listener()

    def _start_listener(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(5)
        t = threading.Thread(target=self._accept_loop, args=(server,))
        t.daemon = True
        t.start()
        print(f"Display server listening on {self.host}:{self.port}")

    def _accept_loop(self, server):
        while True:
            try:
                conn, addr, = server.accept()
                print(f"Display client connected: {addr}")
                with self.lock:
                    self.clients.append(conn)
            except Exception as e:
                print(f"Accept error: {e}")

    def push(self, correlation_data):
        """
        Format and broadcast to all connected display clients.
        correlation_data is the dict from the correlation daemon callback.
        """
        cone_devices = correlation_data.get("cone_device",[])

        payload = {
            "h": round(correlation_data.get("heading") or 0),
            "p": round(correlation_data.get("pitch") or 0),
            "n": correlation_data.get("ambient_count", 0),
            "c": [
                {
                    "m": d["manuf"][:10],
                    "r": d["cone_rssi"] or -99,
                    "d": round(d["confidence"] * 100),
                }
            ]
        }

        line = json.dumps(payload) + "\n"
        encoded = line.encode("utf-8")

        dead = []
        with self.lock:
            for client in self.clients:
                try:
                    client.sendall(encoded)
                except (BrokenPipeError, ConnectionResetError):
                    dead.append(client)
            for d in dead:
                self.clients.remove(d)