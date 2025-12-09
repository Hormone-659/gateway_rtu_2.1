"""简化版报警流程演示 UI。

用途：
- 直接演示你在需求里描述的几条关键报警逻辑：
  1. 任意传感器达到阈值1，或者电参缺一项，或者载荷位移异常 -> 一级报警
  2. 任意传感器达到阈值2，或者电参缺2项 -> 二级报警
  3. 皮带光电/任意振动传感器达到阈值3 且电参&载荷位移正常 -> 仍视作二级报警，并置 sensor_3
  4. 皮带光电达到阈值3 且电参至少缺一项 -> 三级报警，并置 belt_all_3
  5. 任意光电达到阈值3 且电参至少缺一项 -> 三级报警，并置 line_3
- 以文字方式即时显示每一条规则是否被触发，方便教学/自检。

和原有 alarm_ui.py 的区别：
- 不再关心 txt 文件、Modbus，只在界面上实时显示逻辑判断过程；
- 使用 alarm_logic.SensorState 和各个 eval_xxx 函数，逻辑完全一致；
- 所有注释为中文，便于后续维护和扩展。

运行方式：
    cd E:\gateway_RTU\src\gateway\alarm
    python alarm_demo_ui.py
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from alarm_logic import (
    SensorState,
    eval_level1,
    eval_level2_and_sensor3,
    eval_level3,
    build_rtu_registers,
)


class AlarmFlowDemoUI:
    """报警流程演示界面。"""

    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        self.master.title("报警流程演示")

        # 传感器等级
        self.belt_level = tk.IntVar(value=0)
        self.mid_bearing_level = tk.IntVar(value=0)
        self.tail_bearing_level = tk.IntVar(value=0)
        self.horsehead_level = tk.IntVar(value=0)
        self.crank_left_level = tk.IntVar(value=0)
        self.crank_right_level = tk.IntVar(value=0)
        self.line_level = tk.IntVar(value=0)

        # 电参 / 载荷位移
        self.elec_phase_a_ok = tk.BooleanVar(value=True)
        self.elec_phase_b_ok = tk.BooleanVar(value=True)
        self.elec_phase_c_ok = tk.BooleanVar(value=True)
        self.loadpos_ok = tk.BooleanVar(value=True)

        self._build_ui()
        self._update_flow()  # 初始化时刷新一次

    # ------------------------ UI 构建 ------------------------

    def _build_ui(self) -> None:
        root = self.master
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        frame = ttk.Frame(root, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")

        row = 0
        ttk.Label(frame, text="一、传感器等级设置 (0-3)：", font=("SimHei", 11, "bold")).grid(
            row=row, column=0, columnspan=4, sticky="w"
        )
        row += 1

        self._add_level(frame, "皮带光电", self.belt_level, row)
        row += 1
        self._add_level(frame, "中部轴承", self.mid_bearing_level, row)
        row += 1
        self._add_level(frame, "尾部轴承", self.tail_bearing_level, row)
        row += 1
        self._add_level(frame, "驴头", self.horsehead_level, row)
        row += 1
        self._add_level(frame, "左曲柄", self.crank_left_level, row)
        row += 1
        self._add_level(frame, "右曲柄", self.crank_right_level, row)
        row += 1
        ttk.Separator(frame, orient="horizontal").grid(
            row=row, column=0, columnspan=4, sticky="ew", pady=6
        )
        row += 1

        ttk.Label(frame, text="二、电参 / 载荷位移：", font=("SimHei", 11, "bold")).grid(
            row=row, column=0, columnspan=4, sticky="w"
        )
        row += 1

        ttk.Checkbutton(
            frame, text="电参 A 相正常", variable=self.elec_phase_a_ok, command=self._update_flow
        ).grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Checkbutton(
            frame, text="电参 B 相正常", variable=self.elec_phase_b_ok, command=self._update_flow
        ).grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Checkbutton(
            frame, text="电参 C 相正常", variable=self.elec_phase_c_ok, command=self._update_flow
        ).grid(row=row, column=0, sticky="w")
        row += 1
        ttk.Checkbutton(
            frame, text="载荷位移正常", variable=self.loadpos_ok, command=self._update_flow
        ).grid(row=row, column=0, sticky="w")
        row += 1

        ttk.Separator(frame, orient="horizontal").grid(
            row=row, column=0, columnspan=4, sticky="ew", pady=6
        )
        row += 1

        # 按钮：强制刷新一次（也可以依靠每个控件的 command 自动刷新）
        btn_refresh = ttk.Button(frame, text="重新计算报警逻辑", command=self._update_flow)
        btn_refresh.grid(row=row, column=0, sticky="w")
        row += 1

        ttk.Label(frame, text="三、报警规则逐条判断：", font=("SimHei", 11, "bold")).grid(
            row=row, column=0, columnspan=4, sticky="w", pady=(8, 2)
        )
        row += 1

        # 使用只读文本框展示每条规则的当前状态
        self.text_flow = tk.Text(frame, width=90, height=18)
        self.text_flow.grid(row=row, column=0, columnspan=4, sticky="nsew")
        frame.rowconfigure(row, weight=1)

    def _add_level(self, parent: tk.Widget, label: str, var: tk.IntVar, row: int) -> None:
        """添加一行等级调节控件。"""

        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        spin = ttk.Spinbox(
            parent,
            from_=0,
            to=3,
            textvariable=var,
            width=5,
            command=self._update_flow,
        )
        spin.grid(row=row, column=1, sticky="w")

    # ------------------------ 逻辑演示 ------------------------

    def _current_state(self) -> SensorState:
        """从控件读值，构造当前的 SensorState。"""

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

    def _update_flow(self) -> None:
        """重新计算并在文本框中展示每条报警规则当前是否触发。"""

        state = self._current_state()

        # 分别调用三段逻辑，拿到触发标志
        level1_trigger, _ = eval_level1(state)
        level2_trigger, _ = eval_level2_and_sensor3(state)
        level3_trigger, _ = eval_level3(state)

        # 按你给的自然语言规则，一条一条解释
        # 这里不强依赖 Python 3.9+ 的 list[str] 语法，直接使用普通 list，
        # 以兼容部分类型检查器 / 运行环境。
        lines = []  # type: list

        # 先根据当前状态计算一次寄存器，方便展示 3503 故障类型
        regs = build_rtu_registers(state)
        fault_type = regs.get(3503, 0)

        lines.append("【当前输入状态】")
        lines.append(f"  皮带光电等级: {state.belt_level}")
        lines.append(f"  中部轴承等级: {state.mid_bearing_level}")
        lines.append(f"  尾部轴承等级: {state.tail_bearing_level}")
        lines.append(f"  驴头等级: {state.horsehead_level}")
        lines.append(f"  左曲柄等级: {state.crank_left_level}")
        lines.append(f"  右曲柄等级: {state.crank_right_level}")
        lines.append(f"  线路光电等级: {state.line_level}")
        lines.append(
            f"  电参 A/B/C 正常: {state.elec_phase_a_ok}/{state.elec_phase_b_ok}/{state.elec_phase_c_ok}"
        )
        lines.append(f"  载荷位移正常: {state.loadpos_ok}")
        lines.append("")

        # 故障类型寄存器 3503 展示
        lines.append("【故障类型寄存器 3503】")
        lines.append("  编码含义：0=无故障，1=皮带全断，2=光杆毛毡子断，3=传感器故障")
        lines.append(f"  当前 3503 寄存器值: {fault_type}")
        lines.append("")

        # 1 级报警规则
        lines.append("【一级报警规则】")
        lines.append(
            "  规则 1：任意传感器达到阈值1，或者电参缺一项，或者载荷位移异常，则触发一级报警。"
        )
        lines.append(f"  -> 当前结果：{'触发' if level1_trigger else '未触发'}")
        lines.append("")

        # 2 级报警规则（包含传感器3=二级的两种情况）
        lines.append("【二级报警规则】")
        lines.append("  规则 2：任意传感器达到阈值2，或者电参缺2项，则触发二级报警。")
        lines.append(
            "  规则 3：皮带光电达到阈值3，且电参和载荷位移正常，则按二级报警处理，同时 sensor_3=1。"
        )
        lines.append(
            "  规则 4：任意振动传感器达到阈值3，且电参和载荷位移正常，则按二级报警处理，同时 sensor_3=1。"
        )
        lines.append(f"  -> 当前结果（二级总判断）：{'触发' if level2_trigger else '未触发'}")
        lines.append("")

        # 3 级报警规则
        lines.append("【三级报警规则】")
        lines.append(
            "  规则 5：皮带光电传感器达到阈值3，且电参至少缺一项，则触发三级报警，写入 belt_all_3。"
        )
        lines.append(
            "  规则 6：任意振动传感器达到阈值3，且电参至少缺一项，则触发三级报警，写入 level_3.txt，line_3。"
        )
        lines.append(f"  -> 当前结果：{'触发' if level3_trigger else '未触发'}")
        lines.append("")

        # 把文字写入文本框
        self.text_flow.delete("1.0", tk.END)
        self.text_flow.insert("1.0", "\n".join(lines))


def main() -> None:
    root = tk.Tk()
    app = AlarmFlowDemoUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
