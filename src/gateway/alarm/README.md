# 报警模块说明（`src/gateway/alarm`）

本目录负责**抽油机/皮带机报警逻辑**的演示与 RTU 写入，包括：

- 报警逻辑核心实现：根据各传感器等级、电参、载荷位移，计算 1/2/3 级报警和故障类型；
- 报警结果落地到 txt 文件（`alarm_level` 目录），便于对照与联调；
- 把同样的报警结果映射到 RTU 保持寄存器（3501~3520），通过 Modbus TCP 写入现场 RTU；
- 两套主要 UI：
  - `alarm_play/alarm_demo_ui.py`：只演示报警逻辑，不写 RTU；
  - `alarm_play/alarm_rtu_ui.py`：用于实际写 RTU 的联调界面；
- 一个较早的一体化 UI：`alarm_play/alarm_ui.py`（可作为参考）。

> 说明：原来的逻辑文件现在都集中在 `alarm_play/` 子目录下，请以该子目录为准。

---

## 目录结构总览

```text
alarm/
  alarm_play/
    alarm_logic.py       # 报警逻辑核心模块（txt + RTU 寄存器映射）
    alarm_demo_ui.py     # 报警逻辑演示 UI（不写 RTU）
    alarm_rtu_ui.py      # RTU 写入联调 UI（真正发 Modbus 帧）
    alarm_ui.py          # 较老的一体化报警界面（可作为参考）

  alarm_level/           # 各报警等级输出的 txt 文件
    RTU_address_fuc.csv  # Modbus 寄存器映射表（3501~3520）
    level_1/             # 一级报警相关 txt
    level_2/             # 二级报警相关 txt（含 sensor_fault）
    level_3/             # 三级报警及严重故障 txt（belt_all / stick_fault 等）

  README.md              # 本说明
```

---

## 1. `alarm_play/alarm_logic.py` —— 报警逻辑核心

### 1.1 核心职责

`alarm_logic.py` 只做**纯逻辑**，不直接访问 RTU：

1. 定义抽象的**传感器状态模型** `SensorState`：
   - 各传感器报警等级（目前编号和顺序按现场约定）：
     1. `crank_left_level`   —— 曲柄销子_左（振动）
     2. `crank_right_level`  —— 曲柄销子_右（振动）
     3. `tail_bearing_level` —— 尾轴承（振动）
     4. `mid_bearing_level`  —— 中轴承（振动）
     5. `horsehead_level`    —— 驴头（光电/位移相关）
     6. `belt_level`         —— 皮带光电（光电）
     - `line_level`：线路光电等级 (0~3)，目前 UI 不直接控制，可留给后续扩展。
   - 电参状态：
     - `elec_phase_a_ok / elec_phase_b_ok / elec_phase_c_ok`：True=该相正常，False=缺相或异常。
   - 载荷位移：
     - `loadpos_ok`：True=载荷正常，False=载荷异常。

2. 根据 `SensorState` 计算：
   - 一级报警：`eval_level1`
   - 二级报警 + 传感器 3 级故障：`eval_level2_and_sensor3`
   - 三级报警：`eval_level3`
   - 统一对外接口：
     - `evaluate_alarms(state) -> Dict[path_str, "0"/"1"]`：返回所有 txt 文件的写入 0/1 映射；
     - `build_rtu_registers(state) -> Dict[int, int]`：返回所有 RTU 保持寄存器（3501~3520）的整数值；
     - `write_alarm_files(file_map)`：把 `evaluate_alarms` 的结果真正写到磁盘 txt。

3. 保持**无状态**：
   - 调用方只需构建一个 `SensorState` 并传入，本模块不依赖外部 I/O。

### 1.2 报警规则概要

> 以下是为方便联调总结的关键规则，详细实现可直接阅读源码中的中文注释。

#### 1.2.1 一级报警（`eval_level1`）

- 一级触发条件（`level_1/level_1.txt` 写 1）：
  - 任意传感器达到阈值 1，**或**
  - 电参至少缺 1 项，**或**
  - 载荷位移异常；
  - 三者任意组合。
- 相关 txt：
  - `level_1/level_1.txt`：整体一级报警标志；
  - `belt_1.txt` / `mid_bearing_1.txt` / `tail_bearing_1.txt` / `horsehead_1.txt` / `crank_left_1.txt` / `crank_right_1.txt`：对应传感器达到 1 级写 1；
  - `elec_1.txt`：电参至少缺 1 相写 1；
  - `loadpos_1.txt`：载荷异常写 1。

#### 1.2.2 二级报警 + 传感器 3 级故障（`eval_level2_and_sensor3`）

- 二级触发条件（`level_2/level_2.txt` 写 1）：
  1. 任意传感器达到阈值 2；
  2. 电参至少缺 2 项；
  3. 任意传感器达到阈值 3，且电参 **全部正常** 且载荷 **正常**；
  - 满足以上任一条件或任意组合均触发二级报警。
- 传感器故障文件：
  - 当满足条件 (3) 时：
    - `level_2/sensor_fault.txt` 写 1（表示“传感器自身 3 级、但电参/载荷都好”的软故障）；
  - 若有缺相或者载荷异常，则不写 `sensor_fault.txt`，而是进入更高等级逻辑。
- 其它二级 txt：
  - 各传感器 `_2.txt`：达到 2 级即写 1；
  - `elec_2.txt`：电参至少缺 2 相写 1；
  - `loadpos_2.txt`：载荷异常写 1。

#### 1.2.3 三级报警（`eval_level3`）

- 三级触发规则：
  1. **皮带光电传感器** 达到阈值 3，且电参至少缺 1 项：
     - `level_3/level_3.txt` 写 1；
     - `level_3/belt_all.txt` 写 1（皮带严重故障，例如“皮带全断”）。
  2. 任意 **振动传感器**（曲柄销子左右 + 中/尾轴承）达到阈值 3，且电参至少缺 1 项：
     - `level_3/level_3.txt` 写 1；
     - `level_3/stick_fault.txt` 写 1（光杆/振动严重故障）。
- 同时仍然为所有传感器生成对应的 `_3.txt`：达到 3 级写 1。

### 1.3 RTU 寄存器映射（`build_rtu_registers`）

- 根据 `SensorState` 计算出：
  - 电参缺相个数 → `electrical_level`（0=正常, 1=缺1相, 2=缺≥2相）；
  - 载荷是否异常 → `loadpos_level`（0=正常, 1=异常）；
  - 传感器等级、电参等级、载荷等级的最大值 → 整体报警等级（但有“3级+电参载荷正常按 2 级处理”的特殊规则，见下）。

- 整体报警等级（写寄存器 3502）：
  1. 先取所有传感器 + 电参等级 + 载荷等级的最大值，裁剪到 0~3；
  2. 如果出现“任意传感器 3 级，且电参全部正常、载荷正常”的场景：
     - **整体报警等级强制按 2 级处理**，3502 写 2；
     - 配合 `level_2/sensor_fault.txt=1` 表示“传感器 3 级、设备本身还没坏”的场景。

- 故障类型（3504）：根据 3 级和电参情况组合得到：
  - 0：正常；
  - 1：皮带 3 级 + 电参缺项 → 皮带全断类严重故障；
  - 2：任意振动 3 级 + 电参缺项 → 机械/光杆严重故障；
  - 3：传感器 3 级 + 电参正常 → 传感器故障（区别于真实机械故障）。

- 其它寄存器：
  - 3505~3510：对应部位是否故障（达到 1 级以上写 1）；
  - 3513~3518：对应部位的故障等级（0~3）；
  - 3511 / 3519：电参是否故障、电参故障等级；
  - 3512 / 3520：载荷是否故障、载荷故障等级。

寄存器具体定义以 `alarm_level/RTU_address_fuc.csv` 为准，`build_rtu_registers` 已按该表实现。

---

## 2. `alarm_play/alarm_rtu_ui.py` —— RTU 写入联调界面

### 2.1 用途

`alarm_rtu_ui.py` 是一套基于 Tkinter 的联调界面，用于：

1. 通过界面设置各传感器的报警等级、电参状态、载荷是否异常；
2. 调用 `alarm_logic` 计算：
   - txt 文件写入映射；
   - RTU 保持寄存器（3501~3520）的值；
3. 通过原始 Modbus TCP 帧（功能码 06）把这些寄存器写入 RTU；
4. 在界面上显示：
   - 整体报警等级（直接显示寄存器 3502 的值）；
   - 关键 txt 文件（`level_1.txt` / `level_2.txt` / `level_3.txt` / `sensor_fault.txt` 等）的当前 0/1 状态；
   - 实际写入每个寄存器的地址和值，便于和 PLC/RTU 工程对表。

### 2.2 界面结构

1. **RTU 连接参数**：
   - IP 地址、端口、Unit ID；
   - “连接 RTU”/“断开 RTU”按钮；
   - 使用原始 Modbus TCP 协议手动组帧，便于抓包分析。

2. **传感器等级设置 (0~3)**：
   - 皮带光电
   - 中部轴承
   - 尾部轴承
   - 驴头
   - 左曲柄
   - 右曲柄

3. **电参 / 载荷位移**：
   - 电参 A 相正常（勾选为 True）
   - 电参 B 相正常
   - 电参 C 相正常
   - 载荷异常（勾选时内部 `loadpos_ok=False`，表示载荷异常）

4. **报警整体写入 RTU**：
   - “按报警逻辑写入 RTU”按钮：
     1. 用当前界面值构造 `SensorState`；
     2. 调用 `evaluate_alarms` 得到 txt 结果（仅在文本框中展示，不真正写磁盘）；
     3. 调用 `build_rtu_registers` 得到保持寄存器 3501~3520 的值；
     4. 使用功能码 06 逐个写入 RTU；
     5. 顶部文本框中显示整体报警等级和关键 txt 标志。
   - “恢复默认(3501-3520清零)”按钮：
     - 循环调用单寄存器写，把 3501~3520 全部写 0。

5. **单寄存器读写（调试用）**：
   - 指定工程地址（例如 3501，对应 PLC 的 43501）；
   - “读取单寄存器”：使用功能码 03 读取一个保持寄存器；
   - “写入单寄存器”：使用功能码 06 写入一个保持寄存器；
   - 日志输出到下方文本框。

### 2.3 地址基准说明（0 基 / 1 基）

- 界面和 `build_rtu_registers` 都使用 **工程地址**：
  - 例如 3501 表示 PLC 工程中的 43501；
  - 所有寄存器 key 都直接是 3501~3520，方便和 `RTU_address_fuc.csv`、PLC 工程对照。
- 现场 RTU 实际使用 **0 基地址**（常见为 43501 → PDU 地址 3500）：
  - 为了对齐，`_read_holding_single` 和 `_write_holding_single` 在真正发送 Modbus 帧前，统一做了 `address - 1` 的转换：
    - 比如 UI 中填 3501，发帧时使用的 PDU 地址是 3500；
  - 这样可以保证：
    - PLC 工程里 43501 ↔ UI 中的 3501 ↔ 实际 PDU 地址 3500 一一对应，不再出现“整体偏移一位”的现象。

### 2.4 文本框顶部显示内容

写入 RTU 前，`_write_to_rtu` 会先在文本框顶部打印摘要：

- **整体报警等级**：
  - 直接读取 `registers[3502]`，即 RTU 寄存器 3502 的数值；
  - 与 PLC 工程中的 43502 完全一致。
- 关键 txt 文件状态（从 `file_map` 中读取）：
  - `level_1/level_1.txt`
  - `level_2/level_2.txt`
  - `level_3/level_3.txt`
  - 以及 `sensor_fault.txt`、`belt_all.txt`、`stick_fault.txt` 等严重故障标志。

紧接着打印所有寄存器地址和值，便于核对。

---

## 3. `alarm_play/alarm_demo_ui.py` —— 报警逻辑演示界面

### 3.1 用途

- 和 `alarm_rtu_ui.py` 类似，但**不连接 RTU、不写 Modbus**；
- 主要用于：
  - 在离线环境里调节 `SensorState`；
  - 观察 `level_1/2/3` 各 txt 文件的写入结果；
  - 校对业务逻辑是否符合预期（例如“3级 + 电参载荷正常 → 只触发二级 + `sensor_fault`”）。

### 3.2 工作流程（简版）

1. 在 UI 上设置各传感器等级、电参状态、载荷状态；
2. 调用 `alarm_logic.evaluate_alarms` 得到 txt 文件写入映射；
3. 按一定格式展示在文本区域中，或真正调用 `write_alarm_files` 写入 `alarm_level` 目录（取决于具体实现）。

> 推荐：
> - 新业务规则先在 `alarm_demo_ui.py` 中验证，
> - 确认 txt 输出和期望一致后，再用 `alarm_rtu_ui.py` 对接 RTU 寄存器。

---

## 4. `alarm_play/alarm_ui.py` —— 旧版综合 UI（可选）

`alarm_ui.py` 是早期的一体化报警界面，部分逻辑已经被拆分到 `alarm_logic.py` + `alarm_demo_ui.py` + `alarm_rtu_ui.py` 中。

- 如果你是新接手项目，建议：
  - 把 `alarm_ui.py` 当作参考代码阅读；
  - 新功能统一基于 `alarm_play/alarm_logic.py` 和两套 UI 扩展；
  - 避免在旧文件上继续叠加逻辑，以保持结构清晰。

---

## 5. `alarm_level` 目录 —— 报警结果 txt 文件

`alarm_level` 是报警结果落地的地方，方便：

- 本地调试与对表（不用连 RTU 也能看报警结果）；
- 其他系统（比如上位机或脚本）按需读取这些 txt 文件。

主要内容：

- `RTU_address_fuc.csv`：
  - 定义 3501~3520 每个寄存器的含义，与 PLC 工程保持一致；
  - `build_rtu_registers` 的实现即基于此表。

- `level_1/`：一级报警相关文件
  - `level_1.txt`：一级总报警标志
  - `belt_1.txt` / `mid_bearing_1.txt` / ... / `crank_right_1.txt`
  - `elec_1.txt` / `loadpos_1.txt`

- `level_2/`：二级报警相关文件
  - `level_2.txt`：二级总报警标志
  - 各部位 `_2.txt`
  - `elec_2.txt` / `loadpos_2.txt`
  - `sensor_fault.txt`：传感器 3 级 + 电参/载荷正常 时写 1

- `level_3/`：三级报警 + 严重故障文件
  - `level_3.txt`：三级总报警标志
  - 各部位 `_3.txt`
  - `belt_all.txt`：皮带光电 3 级 + 电参缺项
  - `stick_fault.txt`：振动 3 级 + 电参缺项

`alarm_logic.write_alarm_files` 会在路径不存在时自动创建子目录，并只在文件内容变化时写入，减少磁盘 IO。

---

## 6. 推荐使用流程（从调试到现场）

1. **离线调试报警逻辑**：
   - 运行：
     ```bash
     cd src/gateway/alarm
     python alarm_play/alarm_demo_ui.py
     ```
   - 通过 UI 设置不同的传感器等级、电参、载荷组合；
   - 查看 txt 文件映射（界面展示或 `alarm_level` 目录中的实际文件）；
   - 对照业务规则确认：
     - 一级/二级/三级是否按预期触发；
     - `sensor_fault.txt`、`belt_all.txt`、`stick_fault.txt` 等是否在正确场景写 1；
     - 特别关注“3级 + 电参载荷正常 → 只触发二级 + `sensor_fault`”场景。

2. **联调 RTU 寄存器**：
   - 保证现场 RTU 已开通 Modbus TCP，记录 IP、端口和 Unit ID；
   - 运行：
     ```bash
     cd src/gateway/alarm
     python alarm_play/alarm_rtu_ui.py
     ```
   - 在 UI 中配置 IP / 端口 / Unit ID，点击“连接 RTU”；
   - 使用“单寄存器读写”验证 3501 与 PLC 侧 43501 的对应关系，确认地址偏移正确；
   - 点击“按报警逻辑写入 RTU”，在 PLC/RTU 侧核对 3501~3520 的值：
     - 重点关注 3502（整体报警等级）是否和预期一致；
     - 校对 3504（故障类型）、351x（各部件故障/故障等级）等。

3. **现场运行**：
   - 实际项目中，网关程序会：
     1. 周期性从 RTU 读取原始数据；
     2. 计算各传感器的等级、电参状态、载荷状态；
     3. 构造 `SensorState` 并调用：
        - `evaluate_alarms(state)`：如需 txt 输出；
        - `build_rtu_registers(state)`：得到 RTU 寄存器目标值，再写回 RTU 或上传 SCADA；
   - 本目录提供的 UI 主要用于调试和联调，不一定直接用于生产环境。

---

## 7. 后续扩展建议

- 如果将来增加新的传感器：
  - 在 `SensorState` 中增加对应的 `*_level` 字段；
  - 在 `_any_sensor_reach_level` 或 `_any_vibration_reach_level` 的字段列表中加入新字段；
  - 在 `eval_level1/2/3` 中补充对应的 `_1/_2/_3.txt` 映射；
  - 如需映射到 RTU 寄存器，在 `RTU_address_fuc.csv` 中增加行，并在 `build_rtu_registers` 中实现；

- 若需要改变业务规则（例如新增特殊组合）：
  - 优先在 `alarm_play/alarm_logic.py` 中调整逻辑和注释；
  - 再在 `alarm_play/alarm_demo_ui.py` 中验证；
  - 最后在 `alarm_play/alarm_rtu_ui.py` 中对接 RTU，避免直接改 UI 中的业务判断。
