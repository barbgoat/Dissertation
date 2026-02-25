import socket
import time
from typing import Dict, List, Optional, Tuple

from protocol import Beacon, Sack, encode, decode


HOST = "0.0.0.0"
PORT = 5000
SUPERFRAME_DURATION_S = 10


def now_ms() -> int:
    return int(time.time() * 1000)


def now_us() -> int:
    return int(time.time() * 1_000_000)


class Client:
    def __init__(self, sock: socket.socket, addr: Tuple[str, int]):
        self.sock = sock
        self.addr = addr
        self.sock.setblocking(False)
        self.buf = b""

    def close(self) -> None:
        try:
            self.sock.close()
        except Exception:
            pass

    def send_line(self, payload: bytes) -> None:
        # 1 JSON por linha
        self.sock.sendall(payload + b"\n")

    def recv_lines(self) -> List[bytes]:
        lines: List[bytes] = []
        try:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("disconnected")
            self.buf += chunk
        except BlockingIOError:
            return []
        except Exception:
            raise

        while b"\n" in self.buf:
            line, self.buf = self.buf.split(b"\n", 1)
            line = line.strip()
            if line:
                lines.append(line)
        return lines


def main() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(8)
    server.setblocking(False)

    clients: List[Client] = []
    sf_id = 0

    print(f"[{now_ms()} ms] TCP Gateway listening on {HOST}:{PORT}")

    while True:
        # aceitar novas conexões
        while True:
            try:
                sock, addr = server.accept()
                c = Client(sock, addr)
                clients.append(c)
                print(f"[{now_ms()} ms] [TCP] Node connected: {addr}")
            except BlockingIOError:
                break
            except Exception as e:
                print(f"[{now_ms()} ms] [TCP] accept error: {e}")
                break

        if not clients:
            time.sleep(0.05)
            continue

        # BEACON
        beacon = Beacon(sf_id=sf_id, gw_ts=now_us())
        beacon_b = encode(beacon)
        dead: List[Client] = []
        for c in clients:
            try:
                c.send_line(beacon_b)
            except Exception:
                dead.append(c)
        for c in dead:
            print(f"[{now_ms()} ms] [TCP] Node disconnected: {c.addr}")
            c.close()
            clients.remove(c)

        print(f"[{now_ms()} ms] [BEACON] SF {sf_id}")

        # UL collection
        uplinks: Dict[int, dict] = {}
        t0 = time.time()
        while (time.time() - t0) < SUPERFRAME_DURATION_S:
            # aceitar novos durante SF
            while True:
                try:
                    sock, addr = server.accept()
                    c = Client(sock, addr)
                    clients.append(c)
                    print(f"[{now_ms()} ms] [TCP] Node connected: {addr}")
                except BlockingIOError:
                    break
                except Exception:
                    break

            dead = []
            for c in list(clients):
                try:
                    for line in c.recv_lines():
                        msg = decode(line)
                        if msg is None:
                            continue
                        devaddr = msg.get("devaddr")
                        if devaddr is None:
                            continue
                        uplinks[int(devaddr)] = msg
                        print(f"[{now_ms()} ms] [UL] from {devaddr} msg={msg}")
                except Exception:
                    dead.append(c)

            for c in dead:
                print(f"[{now_ms()} ms] [TCP] Node disconnected: {c.addr}")
                c.close()
                try:
                    clients.remove(c)
                except ValueError:
                    pass

            time.sleep(0.002)

        # SACK
        acked = sorted(list(uplinks.keys()))
        sack = Sack(sf_id=sf_id, acked_nodes=acked)
        sack_b = encode(sack)

        dead = []
        for c in clients:
            try:
                c.send_line(sack_b)
            except Exception:
                dead.append(c)
        for c in dead:
            print(f"[{now_ms()} ms] [TCP] Node disconnected: {c.addr}")
            c.close()
            try:
                clients.remove(c)
            except ValueError:
                pass

        print(f"[{now_ms()} ms] [SACK] ACK {acked}")
        sf_id += 1


if __name__ == "__main__":
    main()