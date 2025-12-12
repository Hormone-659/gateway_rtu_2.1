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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from core.alarm.alarm_engine import AlarmEngine, FaultLevels
from services.rtu_comm import RtuWriter

DEFAULT_STATE_PATH = Path("/tmp/sensor_fault_state.json")


@dataclass
class _LocationSnapshot:
    value: float
    level: int


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

    def _load_state(self) -> Dict[str, _LocationSnapshot]:
        try:
            with self._state_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as exc:  # noqa: BLE001
            print(f"[alarm_service] Failed to read state: {exc}", file=sys.stderr)
            return {}

        try:
            cl = data["crank_left"]
            cr = data["crank_right"]
            tb = data["tail_bearing"]
            mb = data["mid_bearing"]
        except KeyError:
            return {}

        return {
            "crank_left": _LocationSnapshot(cl["value"], cl["level"]),
            "crank_right": _LocationSnapshot(cr["value"], cr["level"]),
            "tail_bearing": _LocationSnapshot(tb["value"], tb["level"]),
            "mid_bearing": _LocationSnapshot(mb["value"], mb["level"]),
        }

    def _process_once(self) -> None:
        snapshots = self._load_state()
        if not snapshots:
            return

        faults = FaultLevels(
            crank_left=snapshots["crank_left"].level,
            crank_right=snapshots["crank_right"].level,
            tail_bearing=snapshots["tail_bearing"].level,
            mid_bearing=snapshots["mid_bearing"].level,
        )
        alarm_level, rtu_registers = self._engine.evaluate(faults)

        # Write to RTU and log internally.
        self._rtu.write_registers(rtu_registers, alarm_level)

    def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self._process_once()
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
    service = AlarmService()
    _install_signal_handlers(service)
    service.run_forever()


if __name__ == "__main__":
    main()
