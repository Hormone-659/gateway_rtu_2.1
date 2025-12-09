"""网关与 RTU 报警逻辑模块。

本模块只负责：
- 建模传感器状态（SensorState）
- 根据传感器等级、电参、载荷位移等计算 1/2/3 级报警
- 生成需要写入各个报警 txt 文件的内容映射（"0"/"1"）

实际 Modbus 读写应在其它模块中完成：
- 从 RTU 寄存器读取数据
- 计算各传感器当前属于哪一级（0/1/2/3）
- 构造 SensorState 传入本模块的 evaluate_alarms()
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple


# 报警 txt 文件所在的根目录（即 alarm_level 文件夹）
BASE_ALARM_DIR = Path(__file__).parent / "alarm_level"


@dataclass
class SensorState:
    """从 RTU 抽象出来的当前状态。

    *_level 字段：0/1/2/3 表示对应传感器当前达到的报警等级。
    布尔字段：True 表示正常，False 表示缺失/异常。
    """

    # 光电 / 皮带 / 振动传感器等级（0-3）
    belt_level: int = 0          # 皮带光电传感器等级
    mid_bearing_level: int = 0   # 中部轴承振动等级
    tail_bearing_level: int = 0  # 尾部轴承振动等级
    horsehead_level: int = 0     # 驴头振动等级
    crank_left_level: int = 0    # 左曲柄振动等级
    crank_right_level: int = 0   # 右曲柄振动等级
    line_level: int = 0          # 线路光电等级

    # 三相电参是否正常（True=正常，False=缺失或异常）
    elec_phase_a_ok: bool = True
    elec_phase_b_ok: bool = True
    elec_phase_c_ok: bool = True

    # 载荷位移是否正常（True=正常，False=异常）
    loadpos_ok: bool = True


# ---------------------------- 辅助判断函数 -----------------------------


def _any_sensor_reach_level(state: SensorState, level: int) -> bool:
    """任意一个传感器达到指定报警等级 level 即返回 True。

    传感器编号及顺序按现场约定：
    1. 曲柄销子_左  (crank_left_level)   —— 振动传感器
    2. 曲柄销子_右  (crank_right_level)  —— 振动传感器
    3. 尾轴承       (tail_bearing_level) —— 振动传感器
    4. 中轴承       (mid_bearing_level)  —— 振动传感器
    5. 驴头         (horsehead_level)    —— 光电/位移相关
    6. 皮带光电     (belt_level)         —— 光电传感器

    如需将线路光电(line_level)计入“任意传感器”，可在列表中追加。
    """

    return any(
        getattr(state, name) >= level
        for name in [
            "crank_left_level",   # 1
            "crank_right_level",  # 2
            "tail_bearing_level", # 3
            "mid_bearing_level",  # 4
            "horsehead_level",    # 5
            "belt_level",         # 6
            # 需要时可把线路光电也作为传感器参与
            # "line_level",
        ]
    )


def _any_vibration_reach_level(state: SensorState, level: int) -> bool:
    """任意一个振动相关传感器达到指定报警等级 level 即返回 True。

    振动传感器按编号顺序：1 左曲柄、2 右曲柄、3 尾轴承、4 中轴承。
    """

    return any(
        getattr(state, name) >= level
        for name in [
            "crank_left_level",   # 1
            "crank_right_level",  # 2
            "tail_bearing_level", # 3
            "mid_bearing_level",  # 4
        ]
    )


def _any_photoelectric_reach_level3(state: SensorState) -> bool:
    """判断任意光电传感器（皮带 + 线路）是否达到 3 级。"""

    return state.belt_level >= 3 or state.line_level >= 3


def _belt_photoelectric_reach_level3(state: SensorState) -> bool:
    """判断皮带光电传感器是否达到 3 级。"""

    return state.belt_level >= 3


def _electrical_missing_count(state: SensorState) -> int:
    """统计电参缺失的相数（0~3）。"""

    return sum(
        [
            not state.elec_phase_a_ok,
            not state.elec_phase_b_ok,
            not state.elec_phase_c_ok,
        ]
    )


def _electrical_missing_at_least_one(state: SensorState) -> bool:
    """电参至少缺 1 项。"""

    return _electrical_missing_count(state) >= 1


def _electrical_missing_at_least_two(state: SensorState) -> bool:
    """电参至少缺 2 项。"""

    return _electrical_missing_count(state) >= 2


def _electrical_all_ok(state: SensorState) -> bool:
    """电参三相全部正常。"""

    return _electrical_missing_count(state) == 0


def _loadpos_abnormal(state: SensorState) -> bool:
    """载荷位移异常。"""

    return not state.loadpos_ok


def _loadpos_normal(state: SensorState) -> bool:
    """载荷位移正常。"""

    return state.loadpos_ok


def _logical_path(*parts: str) -> str:
    """生成 alarm_level 目录下某个 txt 的完整路径字符串。"""

    return str(BASE_ALARM_DIR.joinpath(*parts))


# --------------------------- 一级报警判断 ---------------------------


def eval_level1(state: SensorState) -> Tuple[bool, Dict[str, str]]:
    """计算一级报警是否触发，并返回 (是否触发, 需要写入的文件字典)。

    约定：
    - 传感器、电参、载荷到达阈值 1，就写对应的 *_1.txt 文件；
    - 一级报警触发条件（写 level_1.txt=1）：
        任意传感器达到阈值 1，或者电参缺 1 项，或者载荷位移异常，三者任意组合。
    """

    # 是否有一级报警
    l1_trigger = (
        _any_sensor_reach_level(state, 1)
        or _electrical_missing_at_least_one(state)
        or _loadpos_abnormal(state)
    )

    files: Dict[str, str] = {}

    # 一级总报警文件
    files[_logical_path("level_1", "level_1.txt")] = "1" if l1_trigger else "0"

    # 各传感器一级文件：达到阈值 1 就写 *_1.txt=1
    files[_logical_path("level_1", "belt_1.txt")] = "1" if state.belt_level >= 1 else "0"
    files[_logical_path("level_1", "mid_bearing_1.txt")] = (
        "1" if state.mid_bearing_level >= 1 else "0"
    )
    files[_logical_path("level_1", "tail_bearing_1.txt")] = (
        "1" if state.tail_bearing_level >= 1 else "0"
    )
    files[_logical_path("level_1", "horsehead_1.txt")] = (
        "1" if state.horsehead_level >= 1 else "0"
    )
    files[_logical_path("level_1", "crank_left_1.txt")] = (
        "1" if state.crank_left_level >= 1 else "0"
    )
    files[_logical_path("level_1", "crank_right_1.txt")] = (
        "1" if state.crank_right_level >= 1 else "0"
    )

    # 电参 / 载荷位移一级：达到阈值 1（电参缺1项 / 载荷异常）就写 1
    files[_logical_path("level_1", "elec_1.txt")] = (
        "1" if _electrical_missing_at_least_one(state) else "0"
    )
    files[_logical_path("level_1", "loadpos_1.txt")] = (
        "1" if _loadpos_abnormal(state) else "0"
    )

    return l1_trigger, files


# ---------------------- 二级报警 + sensor_3 判断 --------------------


def eval_level2_and_sensor3(state: SensorState) -> Tuple[bool, Dict[str, str]]:
    """计算二级报警以及传感器故障文件的写入。

    约定：
    - 传感器、电参、载荷到达阈值 2，就写对应的 *_2.txt 文件；
    - 二级报警触发条件（写 level_2.txt=1）：
        1) 任意传感器达到阈值 2；
        2) 电参缺 2 项；
        3) 任意传感器达到阈值 3，且电参和载荷位移正常；
       以上任一条件或任意组合。
    - 当满足条件 3 时，同时写 sensor_fault.txt=1。
    """

    # 条件 1：任意传感器达到阈值 2
    cond_sensor_lvl2 = _any_sensor_reach_level(state, 2)

    # 条件 2：电参缺 2 项
    cond_elec_two_missing = _electrical_missing_at_least_two(state)

    # 条件 3：任意传感器达到阈值 3，且电参和载荷位移正常
    any_sensor_lvl3 = _any_sensor_reach_level(state, 3)
    cond_lvl3_but_normal = any_sensor_lvl3 and _electrical_all_ok(state) and _loadpos_normal(state)

    l2_trigger = cond_sensor_lvl2 or cond_elec_two_missing or cond_lvl3_but_normal

    files: Dict[str, str] = {}

    # 二级总报警文件
    files[_logical_path("level_2", "level_2.txt")] = "1" if l2_trigger else "0"

    # 各传感器二级文件：达到阈值 2 就写 *_2.txt=1
    files[_logical_path("level_2", "belt_2.txt")] = "1" if state.belt_level >= 2 else "0"
    files[_logical_path("level_2", "mid_bearing_2.txt")] = (
        "1" if state.mid_bearing_level >= 2 else "0"
    )
    files[_logical_path("level_2", "tail_bearing_2.txt")] = (
        "1" if state.tail_bearing_level >= 2 else "0"
    )
    files[_logical_path("level_2", "horsehead_2.txt")] = (
        "1" if state.horsehead_level >= 2 else "0"
    )
    files[_logical_path("level_2", "crank_left_2.txt")] = (
        "1" if state.crank_left_level >= 2 else "0"
    )
    files[_logical_path("level_2", "crank_right_2.txt")] = (
        "1" if state.crank_right_level >= 2 else "0"
    )

    # 电参 / 载荷二级
    files[_logical_path("level_2", "elec_2.txt")] = (
        "1" if _electrical_missing_at_least_two(state) else "0"
    )
    files[_logical_path("level_2", "loadpos_2.txt")] = (
        "1" if _loadpos_abnormal(state) else "0"
    )

    # 传感器故障文件：任意传感器达到阈值3 且电参和载荷位移正常
    files[_logical_path("level_2", "sensor_fault.txt")] = "1" if cond_lvl3_but_normal else "0"

    return l2_trigger, files


# --------------------------- 三级报警判断 ---------------------------


def eval_level3(state: SensorState) -> Tuple[bool, Dict[str, str]]:
    """计算三级报警是否触发，并返回文件写入映射。

    约定：
    - 传感器、电参、载荷到达阈值 3，就写对应的 *_3.txt 文件；
    - 三级报警触发规则：
        1) 皮带光电传感器达到阈值 3，且电参至少缺 1 项
           -> 触发三级报警，写 level_3.txt、belt_all.txt；
        2) 任意振动传感器达到阈值 3，且电参至少缺 1 项
           -> 触发三级报警，写 level_3.txt、stick_fault.txt。
    """

    # 皮带光电 3 级 + 电参缺项
    cond_belt_lvl3_elec_bad = _belt_photoelectric_reach_level3(state) and _electrical_missing_at_least_one(state)

    # 任意振动传感器 3 级 + 电参缺项
    cond_any_vib_lvl3_elec_bad = _any_vibration_reach_level(state, 3) and _electrical_missing_at_least_one(state)

    l3_trigger = cond_belt_lvl3_elec_bad or cond_any_vib_lvl3_elec_bad

    files: Dict[str, str] = {}

    # 三级总报警文件
    files[_logical_path("level_3", "level_3.txt")] = "1" if l3_trigger else "0"

    # 皮带严重故障：belt_all.txt
    files[_logical_path("level_3", "belt_all.txt")] = "1" if cond_belt_lvl3_elec_bad else "0"

    # 振动严重故障：stick_fault.txt
    files[_logical_path("level_3", "stick_fault.txt")] = "1" if cond_any_vib_lvl3_elec_bad else "0"

    # 各传感器 3 级文件：达到阈值 3 就写 *_3.txt=1
    files[_logical_path("level_3", "belt_3.txt")] = "1" if state.belt_level >= 3 else "0"
    files[_logical_path("level_3", "mid_bearing_3.txt")] = (
        "1" if state.mid_bearing_level >= 3 else "0"
    )
    files[_logical_path("level_3", "tail_bearing_3.txt")] = (
        "1" if state.tail_bearing_level >= 3 else "0"
    )
    files[_logical_path("level_3", "horsehead_3.txt")] = (
        "1" if state.horsehead_level >= 3 else "0"
    )
    files[_logical_path("level_3", "crank_left_3.txt")] = (
        "1" if state.crank_left_level >= 3 else "0"
    )
    files[_logical_path("level_3", "crank_right_3.txt")] = (
        "1" if state.crank_right_level >= 3 else "0"
    )

    return l3_trigger, files


# ----------------------------- 对外公共函数 -----------------------------


def evaluate_alarms(state: SensorState) -> Dict[str, str]:
    """综合计算 1/2/3 级报警，返回“文件路径 -> 写入值”的字典。"""

    _, f1 = eval_level1(state)
    _, f2 = eval_level2_and_sensor3(state)
    _, f3 = eval_level3(state)

    merged: Dict[str, str] = {}
    merged.update(f1)
    merged.update(f2)
    merged.update(f3)
    return merged


def write_alarm_files(file_map: Dict[str, str]) -> None:
    """将报警结果写入对应 txt 文件。

    仅当文件内容发生变化时才真正写磁盘，减少磁盘 IO。
    可在轮询循环中反复调用。
    """

    for path_str, value in file_map.items():
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            prev = path.read_text(encoding="utf-8") if path.exists() else None
        except OSError:
            prev = None
        if prev != value:
            path.write_text(value, encoding="utf-8")


def build_rtu_registers(state: SensorState) -> Dict[int, int]:
    """根据当前状态构造 RTU 保持寄存器写入字典（modbus 地址 -> 值）。

    寄存器对应关系以 `RTU_address_fuc.csv` 为准，现版本为：

    3501  抽油机运行状态 pumping_unit_operating_status  0=运行，1=停机
    3502  报警等级 alarm_level                           0=正常，1/2/3 级
    3503  刹车状态 brake_status                          0=松开，1=刹紧，2=故障
    3504  故障类型 fault_type                            0=正常，1=皮带全断，2=光杆毛辫子断，3=传感器故障
    3505  曲柄销子_左 left_crank_pin                     0=正常，1=故障
    3506  曲柄销子_右 right_crank_pin                    0=正常，1=故障
    3507  尾轴承 rear_bearing                            0=正常，1=故障
    3508  中轴承 intermediate_bearing                    0=正常，1=故障
    3509  驴头 horsehead                                 0=正常，1=故障
    3510  皮带 drive_belt                                0=正常，1=故障
    3511  三相电参 three_phase_electrical_params         0=正常，1=故障
    3512  载荷/位移 load_and_displacement                0=正常，1=故障
    3513  曲柄销子_左_故障等级 left_crank_pin_fault_level         0~3
    3514  曲柄销子_右_故障等级 right_crank_pin_fault_level        0~3
    3515  尾轴承_故障等级 rear_bearing_fault_level               0~3
    3516  中轴承_故障等级 intermediate_bearing_fault_level       0~3
    3517  驴头_故障等级 horsehead_fault_level                    0~3
    3518  皮带_故障等级 drive_belt_fault_level                   0~3 (0正常，1/2/3=断1/2/3根)
    3519  三相电参_故障等级 three_phase_electrical_param_fault_level 0=正常，1=缺1相，2=缺所有
    3520  载荷/位移_故障等级 load_displacement_fault_level       0=正常，1=异常

    返回的字典可以直接用于 Modbus TCP 单寄存器写入（功能码 06）。
    """

    registers: Dict[int, int] = {}

    # ------------------------ 电参 / 载荷等中间量 ------------------------

    missing_count = _electrical_missing_count(state)

    # 电参故障等级：0=正常，1=缺1相，2=缺所有（>=2 相）
    if missing_count <= 0:
        electrical_level = 0
    elif missing_count == 1:
        electrical_level = 1
    else:
        electrical_level = 2

    # 载荷位移等级：0=正常，1=异常
    loadpos_level = 1 if _loadpos_abnormal(state) else 0

    # 整体报警等级：所有传感器等级 + 电参等级 + 载荷等级 取最大值，限制在 0~3
    overall_alarm_level = max(
        0,
        state.belt_level,
        state.mid_bearing_level,
        state.tail_bearing_level,
        state.horsehead_level,
        state.crank_left_level,
        state.crank_right_level,
        state.line_level,
        electrical_level,
        loadpos_level,
    )
    if overall_alarm_level > 3:
        overall_alarm_level = 3

    # 特殊规则：任意传感器达到 3 级且电参、载荷位移均正常时，
    # 整体报警按二级处理（3502 写 2），不再写 3 级。
    any_sensor_lvl3 = _any_sensor_reach_level(state, 3)
    cond_lvl3_but_normal = any_sensor_lvl3 and _electrical_all_ok(state) and _loadpos_normal(state)
    if cond_lvl3_but_normal and overall_alarm_level >= 3:
        overall_alarm_level = 2

    # 工具函数：将任意整数裁剪到 [0, max_val]
    def _clamp(value: int, max_val: int) -> int:
        if value < 0:
            return 0
        if value > max_val:
            return max_val
        return value

    # ------------------------ 寄存器填值（0-based 地址） ------------------------
    # 注意：下列註釋中的「modbus 地址」均來自 CSV，這裡直接使用該地址作為 key，
    # 方便與現場 RTU / PLC 對照，不再減 1。

    # 1. 抽油机运行状态 pumping_unit_operating_status，0=运行，1=停机
    # 暂无实际信号，默认写 0 表示“运行”。如果后续接入实际信号，可在此处改写。
    registers[3501] = 0

    # 2. 报警等级 alarm_level，0=正常，1/2/3 级
    registers[3502] = _clamp(overall_alarm_level, 3)

    # 3. 刹车状态 brake_status，0=松开，1=刹紧，2=故障。目前未接入，固定 0。
    registers[3503] = 0

    # 4. 故障类型 fault_type，0=正常，1=皮带全断，2=光杆毛辫子断，3=传感器故障
    fault_type = 0

    any_vib_lvl3 = _any_vibration_reach_level(state, 3)
    belt_lvl3 = state.belt_level >= 3
    elec_bad = _electrical_missing_at_least_one(state)

    # 皮带全断：皮带 3 级且电参异常
    if belt_lvl3 and elec_bad:
        fault_type = 1

    # 任意振动 3 级且电参正常 → 二级报警场景下的“振动传感器故障”（3）
    if any_vib_lvl3 and _electrical_all_ok(state):
        fault_type = 3

    # 皮带 3 级且电参正常 → 二级报警场景下的“皮带传感器故障”（3）
    if belt_lvl3 and _electrical_all_ok(state):
        fault_type = 3

    # 任意振动 3 级且电参异常 → 三级报警场景下的“光杆/机械严重故障”（2）
    if any_vib_lvl3 and elec_bad:
        fault_type = 2

    registers[3504] = fault_type

    # 5. 曲柄销子_左 left_crank_pin，0=正常，1=故障（达到 1 级及以上视为故障）
    registers[3505] = 1 if state.crank_left_level >= 1 else 0

    # 6. 曲柄销子_右 right_crank_pin
    registers[3506] = 1 if state.crank_right_level >= 1 else 0

    # 7. 尾轴承 rear_bearing
    registers[3507] = 1 if state.tail_bearing_level >= 1 else 0

    # 8. 中轴承 intermediate_bearing
    registers[3508] = 1 if state.mid_bearing_level >= 1 else 0

    # 9. 驴头 horsehead
    registers[3509] = 1 if state.horsehead_level >= 1 else 0

    # 10. 皮带 drive_belt
    registers[3510] = 1 if state.belt_level >= 1 else 0

    # 11. 三相电参 three_phase_electrical_params，0=正常，1=故障（缺相数>=1 视为故障）
    registers[3511] = 1 if missing_count >= 1 else 0

    # 12. 载荷、位移 load_and_displacement，0=正常，1=故障
    registers[3512] = 1 if _loadpos_abnormal(state) else 0

    # 13. 曲柄销子_左_故障等级 left_crank_pin_fault_level，0~3
    registers[3513] = _clamp(state.crank_left_level, 3)

    # 14. 曲柄销子_右_故障等级 right_crank_pin_fault_level，0~3
    registers[3514] = _clamp(state.crank_right_level, 3)

    # 15. 尾轴承_故障等级 rear_bearing_fault_level，0~3
    registers[3515] = _clamp(state.tail_bearing_level, 3)

    # 16. 中轴承_故障等级 intermediate_bearing_fault_level，0~3
    registers[3516] = _clamp(state.mid_bearing_level, 3)

    # 17. 驴头_故障等级 horsehead_fault_level，0~3
    registers[3517] = _clamp(state.horsehead_level, 3)

    # 18. 皮带_故障等级 drive_belt_fault_level，0=正常，1/2/3=断 1/2/3 根
    registers[3518] = _clamp(state.belt_level, 3)

    # 19. 三相电参_故障等级 three_phase_electrical_param_fault_level
    # 0=正常，1=缺1相，2=缺所有
    registers[3519] = _clamp(electrical_level, 2)

    # 20. 载荷、位移_故障等级 load_displacement_fault_level，0=正常，1=异常
    registers[3520] = 1 if _loadpos_abnormal(state) else 0

    return registers


if __name__ == "__main__":
    # 簡單自測：構造幾種狀態，打印將要寫入的文件和值（不會真正寫入）
    demo_states = {
        "all_normal": SensorState(),                 # 全部正常
        "belt_lvl1": SensorState(belt_level=1),      # 皮帶 1 級
        "belt_lvl2": SensorState(belt_level=2),      # 皮帶 2 級
        "belt_lvl3_normal": SensorState(belt_level=3),               # 皮帶 3 級，電參&載荷默認正常
        "belt_lvl3_elec_bad": SensorState(belt_level=3, elec_phase_a_ok=False),  # 皮帶 3 級 + 電參缺相
    }

    for name, st in demo_states.items():
        print(f"=== 演示狀態: {name} ===")
        fm = evaluate_alarms(st)
        for p, v in sorted(fm.items()):
            print(p, "->", v)
        # 額外打印對應的 RTU 寄存器寫入建議
        regs = build_rtu_registers(st)
        print("RTU registers (address -> value):")
        for addr in sorted(regs):
            print(f"  {addr} -> {regs[addr]}")
        print()
