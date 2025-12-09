"""简单的报警模拟 UI 界面（使用 Tkinter）。

功能：
- 在界面上调节各传感器的报警等级（0/1/2/3）、电参是否正常、载荷位移是否正常；
- 调用 alarm_logic.evaluate_alarms 计算报警等级；
- 将结果写入 alarm_level 目录下各个 txt 文件；
- 预留 Modbus TCP 写入 RTU 寄存器的接口（如需要可后续补充真实地址）。

说明：
- 该 UI 主要用于本地调试和演示，不适合作为长期在线监控界面；
- 运行方式：
    cd E:\gateway_RTU\src\gateway\alarm
    python alarm_ui.py
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from src.gateway.alarm.alarm_play.alarm_logic import SensorState, evaluate_alarms, write_alarm_files, build_rtu_registers


class AlarmSimulatorUI:
    """报警逻辑模拟界面。"""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        self.master.title("报警逻辑模拟器（网关-RTU）")

        # 各个输入控件的变量
        self.belt_level = tk.IntVar(value=0)
        self.mid_bearing_level = tk.IntVar(value=0)
        self.tail_bearing_level = tk.IntVar(value=0)
        self.horsehead_level = tk.IntVar(value=0)
        self.crank_left_level = tk.IntVar(value=0)
        self.crank_right_level = tk.IntVar(value=0)
        self.line_level = tk.IntVar(value=0)

        self.elec_phase_a_ok = tk.BooleanVar(value=True)
        self.elec_phase_b_ok = tk.BooleanVar(value=True)
        self.elec_phase_c_ok = tk.BooleanVar(value=True)
        self.loadpos_ok = tk.BooleanVar(value=True)

        self._build_ui()

    # --------------------------- UI 构建 ---------------------------

    def _build_ui(self) -> None:
        """搭建界面布局。"""

        frame = ttk.Frame(self.master, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")

        # 让窗口在放大时自动拉伸
        self.master.rowconfigure(0, weight=1)
        self.master.columnconfigure(0, weight=1)

        row = 0

        ttk.Label(frame, text="传感器等级（0-3）：").grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        # 每个传感器一行：标签 + Spinbox
        self._add_level_spinbox(frame, "皮带光电", self.belt_level, row)
        row += 1
        self._add_level_spinbox(frame, "中部轴承", self.mid_bearing_level, row)
        row += 1
        self._add_level_spinbox(frame, "尾部轴承", self.tail_bearing_level, row)
        row += 1
        self._add_level_spinbox(frame, "马头", self.horsehead_level, row)
        row += 1
        self._add_level_spinbox(frame, "左曲柄", self.crank_left_level, row)
        row += 1
        self._add_level_spinbox(frame, "右曲柄", self.crank_right_level, row)
        row += 1
        self._add_level_spinbox(frame, "线路光电", self.line_level, row)
        row += 1

        ttk.Separator(frame, orient="horizontal").grid(row=row, column=0, columnspan=3, pady=8, sticky="ew")
        row += 1

        ttk.Label(frame, text="电参 / 载荷位移状态：").grid(row=row, column=0, columnspan=2, sticky="w")
        row += 1

        ttk.Checkbutton(frame, text="电参 A 相正常", variable=self.elec_phase_a_ok).grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="电参 B 相正常", variable=self.elec_phase_b_ok).grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="电参 C 相正常", variable=self.elec_phase_c_ok).grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Checkbutton(frame, text="载荷位移正常", variable=self.loadpos_ok).grid(row=row, column=0, sticky="w")
        row += 1

        ttk.Separator(frame, orient="horizontal").grid(row=row, column=0, columnspan=3, pady=8, sticky="ew")
        row += 1

        # 按钮区域
        btn_eval = ttk.Button(frame, text="计算并写入报警文件", command=self.on_evaluate)
        btn_eval.grid(row=row, column=0, sticky="ew")

        # 新增：写入 RTU 的按钮
        btn_rtu = ttk.Button(frame, text="写入 RTU (192.168.0.200)", command=self.on_write_rtu)
        btn_rtu.grid(row=row, column=1, sticky="ew")

        btn_quit = ttk.Button(frame, text="退出", command=self.master.destroy)
        btn_quit.grid(row=row, column=2, sticky="ew")
        row += 1

        # 结果显示框
        self.text_result = tk.Text(frame, width=80, height=20)
        self.text_result.grid(row=row, column=0, columnspan=3, pady=(8, 0), sticky="nsew")

        # 让结果框可以随窗口拉伸
        frame.rowconfigure(row, weight=1)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

    def _add_level_spinbox(self, parent: tk.Widget, label: str, var: tk.IntVar, row: int) -> None:
        """添加一个数值调节框（0-3）。"""

        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        spin = ttk.Spinbox(parent, from_=0, to=3, textvariable=var, width=5)
        spin.grid(row=row, column=1, sticky="w")

    # --------------------------- 事件处理 ---------------------------

    def on_evaluate(self) -> None:
        """从界面读取当前设置，计算报警并写入 txt 文件。"""

        try:
            state = self._build_state_from_ui()
        except Exception as exc:  # 理论上不会发生，仅作保护
            messagebox.showerror("错误", f"读取界面参数失败: {exc}")
            return

        # 调用报警逻辑
        file_map = evaluate_alarms(state)

        # 写入 txt 文件
        try:
            write_alarm_files(file_map)
        except Exception as exc:
            messagebox.showerror("错误", f"写入报警文件失败: {exc}")
            return

        # 在界面下方文本框中展示本次计算结果
        self.text_result.delete("1.0", tk.END)
        self.text_result.insert(tk.END, "本次计算的报警文件写入结果如下：\n\n")
        for path, value in sorted(file_map.items()):
            self.text_result.insert(tk.END, f"{path} -> {value}\n")

        # 如果后续需要：在这里可以调用 Modbus 写函数，将 state / 报警结果写入 RTU 寄存器
        # 例如：self._write_to_rtu_via_modbus(state)

    def on_write_rtu(self) -> None:
        """从界面读取当前设置，构造 SensorState，并通过 Modbus TCP 写入 RTU。"""

        try:
            state = self._build_state_from_ui()
        except Exception as exc:
            messagebox.showerror("错误", f"读取界面参数失败: {exc}")
            return

        # 先计算要写入的寄存器字典
        try:
            registers = build_rtu_registers(state)
        except Exception as exc:
            messagebox.showerror("错误", f"生成 RTU 寄存器数据失败: {exc}")
            return

        # 写入 RTU
        self._write_to_rtu_via_modbus(registers)

    def _build_state_from_ui(self) -> SensorState:
        """从当前界面控件读取数值，构造一个 SensorState 对象。"""

        return SensorState(
            belt_level=self.belt_level.get(),
            mid_bearing_level=self.mid_bearing_level.get(),
            tail_bearing_level=self.tail_bearing_level.get(),
            horsehead_level=self.horsehead_level.get(),
            crank_left_level=self.crank_left_level.get(),
            crank_right_level=self.crank_right_level.get(),
            line_level=self.line_level.get(),
            elec_phase_a_ok=self.elec_phase_a_ok.get(),
            elec_phase_b_ok=self.elec_phase_b_ok.get(),
            elec_phase_c_ok=self.elec_phase_c_ok.get(),
            loadpos_ok=self.loadpos_ok.get(),
        )

    # ------------------------ Modbus 写入预留 ------------------------

    def _write_to_rtu_via_modbus(self, registers: dict[int, int]) -> None:
        """将当前状态对应的寄存器字典通过 Modbus TCP 写入 RTU。

        实际地址换算规则：
        - 本工程中 `registers` 的 key 已经是「modbus 地址列 - 1」"""
