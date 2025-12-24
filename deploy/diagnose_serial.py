import sys
import glob
import time
import struct

try:
    import serial
    import serial.rs485
except ImportError:
    print("错误: 未找到 pyserial 模块。")
    print("请使用虚拟环境运行此脚本，例如: /root/venv38/bin/python diagnose_serial.py")
    sys.exit(1)

def calculate_crc(data):
    """计算 Modbus CRC16"""
    crc = 0xFFFF
    for char in data:
        crc ^= char
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return struct.pack('<H', crc)

def scan_ports():
    """扫描系统中可能的串口"""
    patterns = [
        '/dev/ttyUSB*',
        '/dev/ttyACM*',
        '/dev/ttyS*',
        '/dev/ttymxc*',
        '/dev/ttyAMA*',
        '/dev/ttyO*',
        '/dev/ttyWK*',
        '/dev/ttyAP*',
    ]
    ports = []
    for p in patterns:
        found = glob.glob(p)
        ports.extend(found)

    # 过滤掉编号过大的 ttyS (通常是无效的)
    filtered_ports = []
    for p in sorted(ports):
        if "ttyS" in p:
            try:
                suffix = p.replace("/dev/ttyS", "")
                if suffix.isdigit() and int(suffix) < 10:
                    filtered_ports.append(p)
            except ValueError:
                pass
        else:
            filtered_ports.append(p)

    return filtered_ports

def check_modbus_device(ser, slave_id, reg_addr=0):
    """检测指定 ID 的设备是否存在"""
    try:
        # 构建 Modbus RTU 请求帧: 读保持寄存器 (0x03)
        # 格式: [ID] [03] [AddrHi] [AddrLo] [CountHi] [CountLo] [CRCLo] [CRCHi]
        req = struct.pack('>BBHH', slave_id, 3, reg_addr, 1)
        req += calculate_crc(req)

        ser.reset_input_buffer()
        ser.reset_output_buffer()
        ser.write(req)

        # 预期响应: [ID] [03] [Bytes] [DataHi] [DataLo] [CRCLo] [CRCHi] = 7 字节
        # 或者异常响应: [ID] [83] [Err] [CRCLo] [CRCHi] = 5 字节
        resp = ser.read(8)

        if len(resp) < 5:
            return False

        resp_id, resp_func = struct.unpack('>BB', resp[:2])
        if resp_id == slave_id:
            # 只要 ID 匹配且功能码是 03 或 83，就认为设备存在
            if resp_func == 3 or resp_func == 0x83:
                return True
    except Exception:
        pass
    return False

def detect_port_config(port):
    """探测串口的波特率和校验位"""
    baudrates = [9600, 19200, 115200, 4800]
    parities = ['N', 'E'] # 'O' 较少见，先不扫以节省时间

    # 用于探测的常见 ID 和寄存器
    probe_ids = [1, 2, 3, 4, 5, 10]
    probe_regs = [0, 58, 100] # 0:通用, 58:特定传感器, 100:常见起始

    print(f"[*] 正在分析串口配置: {port} ...")

    for baud in baudrates:
        for parity in parities:
            try:
                p_val = serial.PARITY_NONE
                if parity == 'E': p_val = serial.PARITY_EVEN
                elif parity == 'O': p_val = serial.PARITY_ODD

                ser = serial.Serial(port=port, baudrate=baud, bytesize=8, parity=p_val, stopbits=1, timeout=0.1)
                if sys.platform.startswith("linux") and ("ttyS" in port or "ttymxc" in port):
                    try:
                        ser.rs485_mode = serial.rs485.RS485Settings()
                    except Exception:
                        pass

                # 快速探测
                for uid in probe_ids:
                    for reg in probe_regs:
                        if check_modbus_device(ser, uid, reg):
                            print(f"    -> 锁定配置: {baud} {parity} (在 ID={uid} 处响应)")
                            ser.close()
                            return baud, parity
                ser.close()
            except Exception:
                pass
    print(f"    -> 未检测到响应设备")
    return None, None

def scan_devices_on_port(port, baud, parity):
    """在已知配置下扫描所有设备 ID"""
    found_devices = []
    print(f"[*] 正在扫描设备 ID (Port={port}, Baud={baud}, Parity={parity})...")

    try:
        p_val = serial.PARITY_NONE
        if parity == 'E': p_val = serial.PARITY_EVEN
        elif parity == 'O': p_val = serial.PARITY_ODD

        ser = serial.Serial(port=port, baudrate=baud, bytesize=8, parity=p_val, stopbits=1, timeout=0.15)
        if sys.platform.startswith("linux") and ("ttyS" in port or "ttymxc" in port):
            try:
                ser.rs485_mode = serial.rs485.RS485Settings()
            except Exception:
                pass

        # 扫描 ID 1-32 (覆盖常见范围)
        for uid in range(1, 33):
            # 尝试读取几个常见寄存器
            if check_modbus_device(ser, uid, 0) or check_modbus_device(ser, uid, 58):
                print(f"    ✅ 发现设备: ID={uid}")
                found_devices.append(uid)
            # 稍微延时避免总线冲突
            time.sleep(0.02)

        ser.close()
    except Exception as e:
        print(f"    扫描出错: {e}")

    return found_devices

if __name__ == "__main__":
    print("=== 串口设备全扫描工具 ===")
    ports = scan_ports()
    print(f"待扫描串口列表: {ports}")
    print("-" * 40)

    results = {}

    for port in ports:
        baud, parity = detect_port_config(port)
        if baud and parity:
            ids = scan_devices_on_port(port, baud, parity)
            if ids:
                results[port] = {
                    "config": f"{baud}/{8}/{parity}/1",
                    "ids": ids
                }
        print("-" * 40)

    print("\n=== 扫描结果汇总 ===")
    if not results:
        print("未发现任何 Modbus 设备。")
    else:
        for port, info in results.items():
            print(f"串口: {port}")
            print(f"  配置: {info['config']}")
            print(f"  设备 ID: {info['ids']}")
            print("")

