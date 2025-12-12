# core/modbus 目录说明

用于封装 Modbus 通讯相关的核心代码，便于在不同场景（UI、后台服务）复用。

## 文件说明

- `rtu_client.py`
  - 封装了基于 `pymodbus` 的 Modbus RTU 串口客户端。
  - 提供配置数据类 `RtuConfig`，用于描述串口号、波特率、校验位等参数。
  - 提供 `ModbusRtuClient` 类，暴露以下方法：
    - `connect()` / `close()`：打开/关闭串口连接。
    - `unit_id` 属性：切换当前从站地址。
    - `read_holding_registers(address, count)`：读取保持寄存器。
    - `write_single_register(address, value)`：写单个保持寄存器（0x06）。
    - `write_multiple_registers(address, values)`：写多个保持寄存器（0x10）。

后台的采集服务（`services/sensor_service.py`）以及后续的 UI，都可以通过这里的统一接口访问 Modbus RTU 设备。

