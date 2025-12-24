"""Background alarm service: read fault levels and write RTU registers.

This module periodically reads the JSON state file written by sensor_service,
converts fault levels into overall alarm levels and RTU register maps using
core.alarm.alarm_engine, and writes those registers to the RTU/PLC.
"""

from __future__ import annotations

import json
import signal
import sys
import threading
import time
import struct
try:
    import serial
except ImportError:
    serial = None
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from core.alarm.alarm_engine import AlarmEngine, FaultLevels
from services.rtu_comm import RtuWriter

DEFAULT_STATE_PATH = Path("/tmp/sensor_fault_state.json")
ELEC_STATE_PATH = Path("/tmp/elec_params.json")


@dataclass
class _LocationSnapshot:
    value: float
    level: int


@dataclass
class _StateSnapshot:
    crank_left: _LocationSnapshot
    crank_right: _LocationSnapshot
    tail_bearing: _LocationSnapshot
    mid_bearing: _LocationSnapshot
    belt: _LocationSnapshot
    line: _LocationSnapshot
    elec_a: bool
    elec_b: bool
    elec_c: bool


class AlarmService:
    def __init__(
        self,
        state_path: Path = DEFAULT_STATE_PATH,
        interval: float = 1.0,
    ) -> None:
        self._state_path = state_path
        self._interval = interval
        self._stop = threading.Event()
        self._engine = AlarmEngine()
        self._rtu = RtuWriter()
        self._last_alarm_level = -1  # Initialize with an invalid level
        self._last_3501_value: Optional[int] = None

        # PLC Control State
        self._plc_port = '/dev/ttyS1'
        self._plc_baud = 9600
        self._plc_unit = 2
        self._plc_write_addr = 0
        self._plc_ser: Optional[serial.Serial] = None
        self._plc_timer_start = 0
        self._plc_action_done = False
        self._last_val_plc = -1

    def _init_plc_serial(self):
        if not serial:
            print("[alarm_service] pyserial not installed, PLC control disabled", file=sys.stderr)
            return
        try:
            self._plc_ser = serial.Serial(
                port=self._plc_port,
                baudrate=self._plc_baud,
                bytesize=8,
                parity=serial.PARITY_NONE,
                stopbits=1,
                timeout=1.0,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False
            )
            print(f"[alarm_service] PLC Serial {self._plc_port} opened", file=sys.stderr)
        except Exception as e:
            print(f"[alarm_service] Failed to open PLC serial: {e}", file=sys.stderr)

    def _calculate_crc(self, data):
        crc = 0xFFFF
        for pos in data:
            crc ^= pos
            for i in range(8):
                if (crc & 1) != 0:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1
        return struct.pack('<H', crc)

    def _write_plc_robust(self, value):
        if not self._plc_ser:
            self._init_plc_serial()
        if not self._plc_ser:
            return

        try:
            cmd = struct.pack('>B B H H', self._plc_unit, 6, self._plc_write_addr, value)
            full = cmd + self._calculate_crc(cmd)

            self._plc_ser.reset_input_buffer()
            self._plc_ser.reset_output_buffer()
            self._plc_ser.write(full)
            time.sleep(0.05)
            time.sleep(0.2)
            resp = self._plc_ser.read(8)

            if len(resp) == 8:
                print(f"[alarm_service] PLC Write Success: {resp.hex().upper()}", file=sys.stderr)
            else:
                print(f"[alarm_service] PLC Write No Response (len={len(resp)})", file=sys.stderr)

        except Exception as e:
            print(f"[alarm_service] PLC Write Exception: {e}", file=sys.stderr)
            # Try to reopen next time
            try:
                self._plc_ser.close()
            except:
                pass
            self._plc_ser = None

    def _process_plc_control(self, current_rtu_101: int):
        """
        PLC Control Logic:
        - If 101 == 82: Start timer. If > 65s, write 2 to PLC addr 0.
        - If 101 == 81: Immediately write 1 to PLC addr 0.
        """
        if current_rtu_101 is None:
            return

        # State change detection
        if current_rtu_101 != self._last_val_plc:
            print(f"[alarm_service] PLC Control State Change: {self._last_val_plc} -> {current_rtu_101}", file=sys.stderr)
            self._last_val_plc = current_rtu_101
            self._plc_action_done = False
            self._plc_timer_start = 0

            if current_rtu_101 == 82:
                self._plc_timer_start = time.time()
            elif current_rtu_101 == 81:
                print(f"[alarm_service] Trigger PLC Write 1 (Immediate)", file=sys.stderr)
                self._write_plc_robust(1)
                # Also write 0 to 3503
                try:
                    self._rtu.write_registers({3503: 0}, -1)
                    print(f"[alarm_service] Wrote 0 to 3503", file=sys.stderr)
                except Exception as e:
                    print(f"[alarm_service] Failed to write 3503: {e}", file=sys.stderr)
                self._plc_action_done = True

        # Timer logic for 82
        if current_rtu_101 == 82 and not self._plc_action_done:
            elapsed = time.time() - self._plc_timer_start
            print(f"[alarm_service] PLC Timer: {elapsed:.1f}/65.0s", file=sys.stderr)
            if self._plc_timer_start > 0 and (elapsed >= 65):
                print(f"[alarm_service] Trigger PLC Write 2 (Timer > 65s)", file=sys.stderr)
                self._write_plc_robust(2)
                # Also write 1 to 3503
                try:
                    self._rtu.write_registers({3503: 1}, -1)
                    print(f"[alarm_service] Wrote 1 to 3503", file=sys.stderr)
                except Exception as e:
                    print(f"[alarm_service] Failed to write 3503: {e}", file=sys.stderr)
                self._plc_action_done = True

    def _load_state(self) -> Optional[_StateSnapshot]:
        try:
            with self._state_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return None
        except Exception as exc:  # noqa: BLE001
            print(f"[alarm_service] Failed to read state: {exc}", file=sys.stderr)
            return None

        try:
            cl = data["crank_left"]
            cr = data["crank_right"]
            tb = data["tail_bearing"]
            mb = data["mid_bearing"]

            # Read photo sensors, default to 0 if missing (backward compatibility)
            belt_data = data.get("belt", {"value": 0.0, "level": 0})
            line_data = data.get("line", {"value": 0.0, "level": 0})

            # Read electrical status, default to True if missing (backward compatibility)
            ea = data.get("elec_a", True)
            eb = data.get("elec_b", True)
            ec = data.get("elec_c", True)
        except KeyError:
            return None

        return _StateSnapshot(
            crank_left=_LocationSnapshot(cl["value"], cl["level"]),
            crank_right=_LocationSnapshot(cr["value"], cr["level"]),
            tail_bearing=_LocationSnapshot(tb["value"], tb["level"]),
            mid_bearing=_LocationSnapshot(mb["value"], mb["level"]),
            belt=_LocationSnapshot(belt_data["value"], belt_data["level"]),
            line=_LocationSnapshot(line_data["value"], line_data["level"]),
            elec_a=ea,
            elec_b=eb,
            elec_c=ec,
        )

    def _process_once(self) -> None:
        snapshot = self._load_state()
        if not snapshot:
            return

        # 1. Read current RTU registers (101 and 102)
        current_rtu_101 = None
        current_rtu_102 = None
        try:
            # Read 2 registers starting at 101
            vals = self._rtu.read_holding_registers(101, 2)
            if vals and len(vals) >= 1:
                current_rtu_101 = vals[0]
            if vals and len(vals) >= 2:
                current_rtu_102 = vals[1]

            if current_rtu_101 is not None:
                # DEBUG: Print every read to confirm connectivity
                # print(f"[alarm_service] Read RTU 101: {current_rtu_101}, 102: {current_rtu_102}", file=sys.stderr)
                pass
        except Exception as exc:
            print(f"[alarm_service] Failed to read RTU 101/102: {exc}", file=sys.stderr)

        # === PLC Control Logic ===
        if current_rtu_101 is not None:
            self._process_plc_control(current_rtu_101)

        # Logic for 43501 based on 40102
        if current_rtu_102 is not None:
            target_43501 = None
            if current_rtu_102 == 2:
                target_43501 = 0
            elif current_rtu_102 == 1:
                target_43501 = 1

            if target_43501 is not None and target_43501 != self._last_3501_value:
                print(f"[alarm_service] RTU 102 is {current_rtu_102}, writing {target_43501} to 43501...", file=sys.stderr)
                try:
                    self._rtu.write_registers({3501: target_43501}, -1)
                    self._last_3501_value = target_43501
                except Exception as exc:
                    print(f"[alarm_service] Failed to write 43501: {exc}", file=sys.stderr)


        # 2. Convert snapshot to FaultLevels
        levels = FaultLevels(
            crank_left=snapshot.crank_left.level,
            crank_right=snapshot.crank_right.level,
            tail_bearing=snapshot.tail_bearing.level,
            mid_bearing=snapshot.mid_bearing.level,
            belt=snapshot.belt.level,
            line=snapshot.line.level,
            elec_a=snapshot.elec_a,
            elec_b=snapshot.elec_b,
            elec_c=snapshot.elec_c,
        )

        alarm_level, rtu_registers = self._engine.evaluate(levels, current_rtu_101=current_rtu_101)

        # === 关键修改：注入 101 寄存器逻辑 ===
        # 如果是 3 级报警，强制将 101 寄存器设为 82
        # 这样 rtu_registers 字典里就会同时包含 3501~3520 和 101
        if alarm_level == 3:
            rtu_registers[101] = 82

        # === 关键修改：注入 43501 (3501) 寄存器逻辑 ===
        # 确保 evaluate 返回的 registers 不会覆盖我们的 43501 逻辑
        if current_rtu_102 is not None:
            if current_rtu_102 == 2:
                rtu_registers[3501] = 0
            elif current_rtu_102 == 1:
                rtu_registers[3501] = 1

        # Only write to RTU if the alarm level has changed
        if alarm_level != self._last_alarm_level:
            print(f"[alarm_service] Alarm level changed from {self._last_alarm_level} to {alarm_level}. Writing to RTU...", file=sys.stderr)
            self._rtu.write_registers(rtu_registers, alarm_level)
            self._last_alarm_level = alarm_level
        else:
            # Optional: Log that we are skipping write
            # print(f"[alarm_service] Alarm level {alarm_level} unchanged. Skipping RTU write.", file=sys.stderr)
            pass

    def run_forever(self) -> None:
        print(f"[alarm_service] Starting alarm evaluation loop (interval={self._interval}s)...", file=sys.stderr)
        while not self._stop.is_set():
            try:
                self._process_once()
                # 打印心跳日志，确保用户能看到服务在运行
                # 注意：如果 _process_once 成功写入 RTU，rtu_comm 也会打印日志
                # 这里打印是为了覆盖读取失败或无数据的情况
                print(f"[alarm_service] Cycle completed at {time.time():.2f}. Next update in {self._interval}s.", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print(f"[alarm_service] Error: {exc}", file=sys.stderr)
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()


def _install_signal_handlers(service: AlarmService) -> None:
    def handler(signum, frame) -> None:  # type: ignore[override]
        print(f"[alarm_service] Received signal {signum}, stopping...")
        service.stop()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


def main() -> None:
    # Update cycle to 1 second as requested
    service = AlarmService(interval=1.0)
    _install_signal_handlers(service)
    service.run_forever()


if __name__ == "__main__":
    main()
