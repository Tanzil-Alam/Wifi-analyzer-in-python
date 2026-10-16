import os
import sys
import time
import shutil
import threading
import socket
import ctypes
from ctypes import wintypes
import numpy as np

try:
    import msvcrt
except ImportError:
    msvcrt = None

sys.stdout.reconfigure(encoding="utf-8")
os.system("")

BLOCKS = [" ", " ", "▂", "▃", "▄", "▅", "▆", "▇", "█"]
WHITE, DIM, RESET = "\033[97m", "\033[90m", "\033[0m"
iphlp = ctypes.windll.iphlpapi

class MIB_IF_ROW2(ctypes.Structure):
    _fields_ = [
        ('InterfaceLuid', ctypes.c_ulonglong), ('InterfaceIndex', wintypes.DWORD),
        ('InterfaceGuid', ctypes.c_byte * 16), ('Alias', ctypes.c_wchar * 257),
        ('Description', ctypes.c_wchar * 257), ('PhysicalAddressLength', wintypes.DWORD),
        ('PhysicalAddress', ctypes.c_byte * 32), ('PermanentPhysicalAddress', ctypes.c_byte * 32),
        ('Mtu', wintypes.DWORD), ('Type', wintypes.DWORD), ('TunnelType', wintypes.DWORD),
        ('MediaType', wintypes.DWORD), ('PhysicalMediumType', wintypes.DWORD),
        ('AccessType', wintypes.DWORD), ('DirectionType', wintypes.DWORD),
        ('InterfaceAndOperStatusFlags', ctypes.c_byte * 4), ('OperStatus', wintypes.DWORD),
        ('AdminStatus', wintypes.DWORD), ('MediaConnectState', wintypes.DWORD),
        ('NetworkGuid', ctypes.c_byte * 16), ('ConnectionType', wintypes.DWORD),
        ('padding1', wintypes.DWORD), ('TransmitLinkSpeed', ctypes.c_ulonglong),
        ('ReceiveLinkSpeed', ctypes.c_ulonglong), ('InOctets', ctypes.c_ulonglong),
        ('InUcastPkts', ctypes.c_ulonglong), ('InNUcastPkts', ctypes.c_ulonglong),
        ('InDiscards', ctypes.c_ulonglong), ('InErrors', ctypes.c_ulonglong),
        ('InUnknownProtos', ctypes.c_ulonglong), ('InUcastOctets', ctypes.c_ulonglong),
        ('InMulticastOctets', ctypes.c_ulonglong), ('InBroadcastOctets', ctypes.c_ulonglong),
        ('OutOctets', ctypes.c_ulonglong), ('OutUcastPkts', ctypes.c_ulonglong),
        ('OutNUcastPkts', ctypes.c_ulonglong), ('OutDiscards', ctypes.c_ulonglong),
        ('OutErrors', ctypes.c_ulonglong), ('OutUcastOctets', ctypes.c_ulonglong),
        ('OutMulticastOctets', ctypes.c_ulonglong), ('OutBroadcastOctets', ctypes.c_ulonglong),
        ('OutQLen', ctypes.c_ulonglong)
    ]

class MIB_IF_TABLE2(ctypes.Structure):
    _fields_ = [('NumEntries', wintypes.ULONG), ('padding', wintypes.ULONG), ('Table', MIB_IF_ROW2 * 1)]


class NetMonitor:
    def __init__(self):
        self.lock = threading.Lock()
        self.connected = False
        self.kbps = 0.0
        self.ping_ms = 0.0
        self.running = True

    def start(self):
        threading.Thread(target=self._traffic_worker, daemon=True).start()
        threading.Thread(target=self._ping_worker, daemon=True).start()

    def _traffic_worker(self):
        def get_bytes():
            table_ptr = ctypes.POINTER(MIB_IF_TABLE2)()
            if iphlp.GetIfTable2(ctypes.byref(table_ptr)) == 0 and table_ptr:
                num = table_ptr.contents.NumEntries
                arr = ctypes.cast(ctypes.byref(table_ptr.contents.Table), ctypes.POINTER(MIB_IF_ROW2 * num)).contents
                total = sum(r.InOctets + r.OutOctets for r in arr if r.OperStatus == 1)
                iphlp.FreeMibTable(table_ptr)
                return total
            return 0

        last_bytes, last_t = get_bytes(), time.perf_counter()
        while self.running:
            time.sleep(0.12)
            now, cur_bytes = time.perf_counter(), get_bytes()
            dt = max(0.001, now - last_t)
            speed = ((cur_bytes - last_bytes) / 1024.0) / dt if last_bytes > 0 and cur_bytes >= last_bytes else 0.0
            last_bytes, last_t = cur_bytes, now

            with self.lock:
                self.kbps = self.kbps * 0.4 + speed * 0.6

    def _ping_worker(self):
        while self.running:
            try:
                t0 = time.perf_counter()
                s = socket.create_connection(('1.1.1.1', 53), timeout=0.5)
                ms = (time.perf_counter() - t0) * 1000.0
                s.close()
                with self.lock:
                    self.ping_ms, self.connected = round(ms, 1), True
            except:
                with self.lock:
                    self.ping_ms, self.connected = 0.0, False
            time.sleep(0.25)


class TerminalVisualizer:
    def __init__(self):
        self.monitor = NetMonitor()
        self.monitor.start()
        self.history = []
        self.smooth_val = 0.0
        self.frames = 0
        self.bar_w = 2

    def run(self):
        sys.stdout.write("\033[?25l\033[2J")
        sys.stdout.flush()
        try:
            while True:
                t0 = time.perf_counter()
                cols, lines = shutil.get_terminal_size((80, 24))
                self.frames += 1
                
                with self.monitor.lock:
                    conn, kbps, ping = self.monitor.connected, self.monitor.kbps, self.monitor.ping_ms

                if not conn:
                    self.smooth_val *= 0.7
                else:
                    boost = min(0.5, np.log1p(kbps) / 20.0)
                    penalty = 0.15 if ping > 120 else (0.05 if ping == 0 else 0.0)
                    target = np.clip(0.3 + boost - penalty, 0.05, 1.0)
                    self.smooth_val += (target - self.smooth_val) * 0.2

                bar_count = max(6, (cols - 2) // (self.bar_w + 1))
                if len(self.history) != bar_count:
                    self.history = [self.smooth_val] * bar_count
                if self.frames % 2 == 0:
                    self.history.pop(0)
                    self.history.append(self.smooth_val)

                bar_h = max(4, lines - 2)
                pad = max(0, (cols - (bar_count * (self.bar_w + 1) - 1)) // 2)
                
                speed_str = f"{kbps:.0f} KB/s"
                title = f"{WHITE}Connected{RESET}  {speed_str}  {ping:.0f} ms" if conn else f"{DIM}Disconnected  0 KB/s  -- ms{RESET}"
                output = [" " * pad + title]

                steps_arr = (np.clip(self.history, 0, 1) * (bar_h * 8)).astype(int)
                for r in range(bar_h - 1, -1, -1):
                    row_line = [" " * pad]
                    for b in range(bar_count):
                        diff = steps_arr[b] - (r * 8)
                        char = "█" * self.bar_w if diff >= 8 else (" " * self.bar_w if diff <= 0 else BLOCKS[diff] * self.bar_w)
                        row_line.append(f"{WHITE}{char}{RESET}" + (" " if b < bar_count - 1 else ""))
                    output.append("".join(row_line))

                sys.stdout.write("\033[H" + "\n".join(output))
                sys.stdout.flush()

                if msvcrt and msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch in (b"q", b"Q", b"\x03"): break
                    elif ch in (b"p", b"P"): self.bar_w = 1 if self.bar_w == 2 else 2

                time.sleep(max(0.001, (1.0 / 60.0) - (time.perf_counter() - t0)))
        except KeyboardInterrupt:
            pass
        finally:
            self.monitor.running = False
            sys.stdout.write("\033[?25h\033[2J\033[H")
            sys.stdout.flush()


if __name__ == "__main__":
    TerminalVisualizer().run()