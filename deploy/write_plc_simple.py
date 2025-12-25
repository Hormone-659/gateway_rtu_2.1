import serial
import struct
import time
import sys


# 文件路径: deploy/write_plc_simple.py

def calc_crc(data):
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
    return crc


def write_single_coil(ser, unit_id, address, state):
    """发送功能码 05 (写单个线圈)"""
    # Modbus 05 规定: ON=0xFF00, OFF=0x0000
    value = 0xFF00 if state else 0x0000

    # 构造帧: [ID] [05] [AddrHi] [AddrLo] [ValHi] [ValLo] [CRCLo] [CRCHi]
    # struct pack: >B B H H (大端序: ID, Func, Addr, Val)
    pdu = struct.pack('>B B H H', unit_id, 0x05, address, value)

    # 计算 CRC (小端序附加在末尾)
    crc = calc_crc(pdu)
    frame = pdu + struct.pack('<H', crc)

    state_str = "ON" if state else "OFF"
    print(f"[-] 发送: {frame.hex().upper()} (设置 {state_str})")
    ser.write(frame)
    time.sleep(0.2)  # 等待 PLC 响应

    if ser.in_waiting:
        response = ser.read(ser.in_waiting)
        print(f"[-] 接收: {response.hex().upper()}")

        # 简单校验: 长度至少8字节，且功能码正确
        if len(response) >= 8 and response[1] == 0x05:
            print(f"✅ 写入成功: ID={unit_id}, Addr={address}, State={state_str}")
        else:
            print(f"❌ 写入失败: 响应异常")
    else:
        print(f"❌ 写入超时: 无响应")


def main():
    # 默认串口配置
    serial_port = '/dev/ttyS4'
    baud_rate = 9600

    print(f"--- PLC 手动写入工具 (功能码 05 - 线圈) ---")
    print(f"串口配置: {serial_port}, {baud_rate}, 8N1")

    try:
        ser = serial.Serial(serial_port, baud_rate, timeout=1)
    except Exception as e:
        print(f"❌ 无法打开串口 {serial_port}: {e}")
        sys.exit(1)

    try:
        # 1. 初始配置输入
        uid_input = input("请输入站号 (Unit ID) [回车默认 2]: ").strip()
        unit_id = int(uid_input) if uid_input else 2

        addr_input = input("请输入线圈地址 (Address) [回车默认 0]: ").strip()
        address = int(addr_input) if addr_input else 0

        print(f"\n>>> 当前目标: 站号 {unit_id}, 线圈地址 {address}")
        print(">>> 操作说明: 输入 1 (ON) 或 0 (OFF), 输入 'c' 修改配置, 输入 'q' 退出")

        while True:
            val_input = input("\n请输入数值 (1/0) > ").strip()

            if val_input.lower() == 'q':
                break

            if val_input.lower() == 'c':
                # 修改配置逻辑
                uid_new = input(f"请输入新站号 (当前 {unit_id}): ").strip()
                if uid_new: unit_id = int(uid_new)

                addr_new = input(f"请输入新地址 (当前 {address}): ").strip()
                if addr_new: address = int(addr_new)

                print(f">>> 更新目标: 站号 {unit_id}, 线圈地址 {address}")
                continue

            if val_input not in ['0', '1']:
                print("❌ 请输入 1 或 0")
                continue

            state = True if val_input == '1' else False
            write_single_coil(ser, unit_id, address, state)

    except KeyboardInterrupt:
        print("\n用户退出")
    except ValueError:
        print("\n❌ 输入格式错误")
    finally:
        if ser.is_open:
            ser.close()
        print("串口已关闭")


if __name__ == "__main__":
    main()
