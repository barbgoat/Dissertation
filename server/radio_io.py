import time
import serial
from typing import Optional


class RadioIO:
    """
    Transporte Serial por linhas (1 JSON por linha).
    """
    def __init__(self, port: str = "COM3", baud: int = 115200, timeout: float = 0.1):
        self.port = port
        self.baud = baud
        self.timeout = timeout

        self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)

        # Ao abrir a porta, alguns ESP32 reiniciam (DTR/RTS). Dá tempo para boot.
        time.sleep(0.2)

        # Limpa buffers
        try:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass

    def send(self, data: bytes) -> None:
        # 1 frame por linha
        try:
            self.ser.write(data + b"\n")
            self.ser.flush()
        except Exception:
            # se a porta cair, deixa propagar para diagnóstico
            raise

    def receive(self) -> Optional[bytes]:
        # Retorna 1 linha completa (sem \n), ou None
        try:
            if self.ser.in_waiting <= 0:
                return None

            line = self.ser.readline()
            if not line:
                return None

            line = line.strip()
            return line if line else None
        except Exception:
            raise

    def timestamp_us(self) -> int:
        return int(time.time() * 1_000_000)