import sys
import struct
import time

try:
    import serial
except ImportError:
    print("需要安装 pyserial: pip install pyserial")
    sys.exit(1)

def crc16(data: bytes) -> bytes:
    """计算 Modbus CRC16"""
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

def write_plc_register(port, slave_id, address, value):
    """
    向 PLC 写入单个寄存器 (功能码 06)
    :param port: 串口路径，如 /dev/ttyS1
    :param slave_id: 设备 ID
    :param address: 寄存器地址 (0-based)
    :param value: 写入的值 (0-65535)
    """
    print(f"正在连接串口 {port} (9600/8/N/1)...")
    try:
        ser = serial.Serial(
            port=port,
            baudrate=9600,
            bytesize=8,
            parity=serial.PARITY_NONE,
            stopbits=1,
            timeout=3.0
        )
    except Exception as e:
        print(f"无法打开串口: {e}")
        return

    # 构建 Modbus RTU 帧
    # 格式: [ID] [06] [AddrHi] [AddrLo] [ValHi] [ValLo] [CRCLo] [CRCHi]
    # 功能码 06: 写单个保持寄存器
    pdu = struct.pack('>BHH', 0x06, address, value)
    frame_no_crc = struct.pack('B', slave_id) + pdu
    crc = crc16(frame_no_crc)
    request = frame_no_crc + crc

    print(f"发送请求: {request.hex().upper()}")

    ser.reset_input_buffer()
    ser.reset_output_buffer()
    ser.write(request)

    # 稍微等待 PLC 处理
    time.sleep(0.1)

    # 读取响应 (固定 8 字节)
    # 成功响应与请求帧完全一致
    response = ser.read(8)
    ser.close()

    print(f"收到响应: {response.hex().upper()}")

    if len(response) < 8:
        print("❌ 写入失败: 响应超时或数据不完整")
        return

    # 校验响应
    resp_id = response[0]
    resp_func = response[1]

    if resp_id != slave_id:
        print(f"❌ 写入失败: ID 不匹配 (期望 {slave_id}, 收到 {resp_id})")
        return

    if resp_func == 0x86: # 错误响应 (0x06 + 0x80)
        err_code = response[2]
        print(f"❌ 写入失败: PLC 返回异常代码 0x{err_code:02X}")
        return

    if resp_func != 0x06:
        print(f"❌ 写入失败: 功能码不匹配 (期望 06, 收到 {resp_func:02X})")
        return

    # 校验 CRC
    resp_crc = response[-2:]
    calc_crc = crc16(response[:-2])
    if resp_crc != calc_crc:
        print("❌ 写入失败: CRC 校验错误")
        return

    print(f"✅ 写入成功! 设备ID: {slave_id}, 地址: {address}, 写入值: {value}")

if __name__ == "__main__":
    # 目标配置: /dev/ttyS1, ID=2, Addr=0
    TARGET_PORT = '/dev/ttyS1'
    TARGET_ID = 2
    TARGET_ADDR = 0

    # 如果提供了命令行参数，直接使用
    if len(sys.argv) == 2:
        try:
            val = int(sys.argv[1])
            write_plc_register(TARGET_PORT, TARGET_ID, TARGET_ADDR, val)
        except ValueError:
            print("错误: 命令行参数必须是整数")
            sys.exit(1)
    # 否则进入交互式循环
    else:
        print(f"=== PLC 交互式控制工具 ===")
        print(f"目标: {TARGET_PORT} | ID: {TARGET_ID} | Addr: {TARGET_ADDR}")
        print("输入 'q' 或 'exit' 退出")

        while True:
            try:
                user_input = input("\n请输入要写入的值 (0-65535): ").strip()

                if user_input.lower() in ['q', 'exit']:
                    print("退出程序")
                    break

                if not user_input:
                    continue

                val = int(user_input)
                if 0 <= val <= 65535:
                    write_plc_register(TARGET_PORT, TARGET_ID, TARGET_ADDR, val)
                else:
                    print("错误: 值必须在 0-65535 之间")

            except ValueError:
                print("错误: 请输入有效的整数")
            except KeyboardInterrupt:
                print("\n退出程序")
                break
