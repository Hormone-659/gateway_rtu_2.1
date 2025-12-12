# core/alarm 目录说明

封装报警相关的核心逻辑，主要负责：

- 将各个部位的故障等级（0/1/2/3）转换成整体报警等级。
- 生成需要写入 RTU/PLC 的寄存器值。

## 文件说明

- `alarm_engine.py`
  - 对现有的 `gateway.alarm.alarm_play.alarm_logic` 做封装，隐藏具体实现细节，提供简单接口：
    - `FaultLevels` 数据类：
      - 字段包括：`crank_left`、`crank_right`、`tail_bearing`、`mid_bearing`，分别表示曲柄左/右、中轴承/尾轴承的故障等级。
    - `AlarmEngine` 类：
      - 初始化时从 `alarm_logic` 中导入 `SensorState`、`evaluate_alarms`、`build_rtu_registers`。
      - `evaluate(faults: FaultLevels) -> (alarm_level, rtu_registers)`：
        - 根据传入的故障等级构造 `SensorState`；
        - 调用已有报警逻辑计算总报警等级；
        - 生成 RTU 寄存器写入映射（如 3501~3520 等）。

后台报警服务（`services/alarm_service.py`）通过 `AlarmEngine` 统一处理报警与 RTU 写寄存器，不依赖任何 UI 代码。

