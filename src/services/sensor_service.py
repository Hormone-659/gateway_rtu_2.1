"""Background sensor service: Modbus RTU acquisition + threshold evaluation.

This module is intended to run *without* any UI. It periodically reads
vibration sensor data over Modbus RTU, evaluates fault levels using the
threshold engine, and writes the latest fault state to a simple JSON file
that other processes (e.g. alarm_service or a UI) can consume.
"""

from __future__ import annotations

import json
import signal
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict

from core.modbus.rtu_client import ModbusRtuClient, RtuConfig
from core.sensor.threshold_engine import SimpleThresholdConfig, SpeedThresholdEngine
from core.sensor.vibration_model import raw_to_speed


# Where to store the latest fault levels for cross-process sharing.
DEFAULT_STATE_PATH = Path("/tmp/sensor_fault_state.json")


@dataclass
class LocationFaultState:
    value: float
    level: int


@dataclass
class SensorFaultState:
    timestamp: float
    crank_left: LocationFaultState
    crank_right: LocationFaultState
    tail_bearing: LocationFaultState
    mid_bearing: LocationFaultState


class SensorService:
    """Periodic Modbus reader + threshold evaluator."""

    def __init__(
        self,
        port: str,
        unit_ids: Dict[str, int],
        state_path: Path = DEFAULT_STATE_PATH,
        interval: float = 1.0,
    ) -> None:
        self._client = ModbusRtuClient(RtuConfig(port=port))
        self._engine = SpeedThresholdEngine(
            SimpleThresholdConfig(level1=1000.0, level2=2000.0, level3=3000.0)
        )
        self._unit_ids = unit_ids
        self._state_path = state_path
        self._interval = interval
        self._stop = threading.Event()

    def _read_speed_from_unit(self, unit_id: int, address: int) -> float:
        """Read a single speed value (mm/s) from a given unit and register."""

        self._client.unit_id = unit_id
        regs = self._client.read_holding_registers(address, 1)
        return raw_to_speed(regs[0])

    def _acquire_once(self) -> SensorFaultState:
        """Read all configured locations once and compute fault levels."""

        # For now we assume one unit per mechanical location. The mapping from
        # logical location name to (unit_id, register_address) is passed in
        # via unit_ids configuration.
        # You can extend this to support multiple channels per location.
        mapping: Dict[str, int] = {
            "crank_left": self._unit_ids.get("crank_left", 1),
            "crank_right": self._unit_ids.get("crank_right", 2),
            "tail_bearing": self._unit_ids.get("tail_bearing", 3),
            "mid_bearing": self._unit_ids.get("mid_bearing", 4),
        }
        # For simplicity we reuse the same register address for all; adjust as
        # needed to match your actual sensor register map.
        reg_addr = 58  # VX as primary speed channel

        cl_val = self._read_speed_from_unit(mapping["crank_left"], reg_addr)
        cr_val = self._read_speed_from_unit(mapping["crank_right"], reg_addr)
        tb_val = self._read_speed_from_unit(mapping["tail_bearing"], reg_addr)
        mb_val = self._read_speed_from_unit(mapping["mid_bearing"], reg_addr)

        cl_lvl = self._engine.evaluate_single(cl_val)
        cr_lvl = self._engine.evaluate_single(cr_val)
        tb_lvl = self._engine.evaluate_single(tb_val)
        mb_lvl = self._engine.evaluate_single(mb_val)

        ts = time.time()
        return SensorFaultState(
            timestamp=ts,
            crank_left=LocationFaultState(cl_val, cl_lvl),
            crank_right=LocationFaultState(cr_val, cr_lvl),
            tail_bearing=LocationFaultState(tb_val, tb_lvl),
            mid_bearing=LocationFaultState(mb_val, mb_lvl),
        )

    def _write_state(self, state: SensorFaultState) -> None:
        data = asdict(state)
        tmp_path = self._state_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        tmp_path.replace(self._state_path)

    def run_forever(self) -> None:
        """Blocking main loop."""

        while not self._stop.is_set():
            try:
                state = self._acquire_once()
                self._write_state(state)
            except Exception as exc:  # noqa: BLE001
                print(f"[sensor_service] Error: {exc}", file=sys.stderr)
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()


def _install_signal_handlers(service: SensorService) -> None:
    def handler(signum, frame) -> None:  # type: ignore[override]
        print(f"[sensor_service] Received signal {signum}, stopping...")
        service.stop()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


def main() -> None:
    # Basic CLI entrypoint. In a real deployment you may want to read these
    # from a config file or environment variables.
    unit_ids = {
        "crank_left": 1,
        "crank_right": 2,
        "tail_bearing": 3,
        "mid_bearing": 4,
    }
    service = SensorService(port="/dev/ttyS0", unit_ids=unit_ids)
    _install_signal_handlers(service)
    service.run_forever()


if __name__ == "__main__":
    main()
