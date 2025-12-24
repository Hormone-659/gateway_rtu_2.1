import time
import socket
import struct
import serial
import sys

# ================= 配置 =================
RTU_HOST = '12.42.7.135'
RTU_PORT = 502
RTU_UNIT = 1
RTU_REG_ADDR = 100

PLC_PORT = '/dev/ttyS1'
PLC_BAUD = 9600
PLC_UNIT = 2
PLC_WRITE_ADDR = 0


def calculate_crc(data):
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


def read_rtu():
    """读取 Modbus TCP"""
    try:
        # 你的 RTU 读取逻辑保持不变
        req = struct.pack('>HHH B B HH', 1, 0, 6, RTU_UNIT, 3, RTU_REG_ADDR, 1)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect((RTU_HOST, RTU_PORT))
        s.sendall(req)
        resp = s.recv(1024)
        s.close()
        if len(resp) >= 11:
            return struct.unpack('>H', resp[9:11])[0]
    except:
        pass
    return None


def main():
    print("=== 启动: 标准模式 + 延时缓冲 (Universal) ===")

    # 1. 打开串口 (最普通的参数，去掉了 rs485 专用设置)
    try:
        ser = serial.Serial(
            port=PLC_PORT,
            baudrate=PLC_BAUD,
            bytesize=8,
            parity=serial.PARITY_NONE,
            stopbits=1,
            timeout=1.0,
            xonxoff=False,  # 确保关闭软件流控
            rtscts=False,  # 确保关闭硬件流控
            dsrdtr=False
        )
        print(f"[系统] 串口 {PLC_PORT} 打开成功")
    except Exception as e:
        print(f"[系统] 串口打开失败: {e}")
        sys.exit(1)

    last_val = -1
    timer_start = 0
    action_done = False

    while True:
        try:
            # 读取 40101 (100)
            current_val = read_rtu()

            # 状态显示
            msg = f"Val: {current_val}"
            if current_val == 82 and not action_done:
                msg += f" | Wait: {int(time.time() - timer_start)}s"
            print(f"\r[监测] {msg:<40}", end='', flush=True)

            if current_val is not None:
                if current_val != last_val:
                    print(f"\n[状态] 变化: {last_val} -> {current_val}")
                    last_val = current_val
                    action_done = False
                    timer_start = 0

                    if current_val == 82:
                        timer_start = time.time()
                    elif current_val == 81:
                        print(f"[PLC] 触发写入 1...")
                        write_robust(ser, 1)
                        action_done = True

                if current_val == 82 and not action_done:
                    if time.time() - timer_start >= 65:
                        print(f"\n[PLC] 计时结束，触发写入 2...")
                        write_robust(ser, 2)
                        action_done = True


            time.sleep(1)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n[错误] {e}")
            time.sleep(1)

    ser.close()


def write_robust(ser, value):
    """
    健壮的写入函数：依靠延时来解决时序问题
    """
    try:
        cmd = struct.pack('>B B H H', PLC_UNIT, 6, PLC_WRITE_ADDR, value)
        full = cmd + calculate_crc(cmd)

        # 1. 清空残余垃圾
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # 2. 发送数据
        ser.write(full)

        # 3. 【绝对关键】强制等待发送完成
        # 9600波特率下，1字节约1ms。8字节约10ms。
        # 这里给 0.05秒 确保物理信号发完
        time.sleep(0.05)

        # 4. 【绝对关键】等待 PLC 处理和回传
        # PLC 扫描周期通常 10ms-50ms，RS485 总线切换也需要时间
        # 我们给 0.2 秒，这对于自动控制完全可以接受，但能极大提高稳定性
        time.sleep(0.2)

        # 5. 读取响应
        resp = ser.read(8)

        if len(resp) == 8:
            print(f"[PLC] ✅ 成功: {resp.hex().upper()}")
        else:
            # 即使没收到，只要不是死循环，下一次循环可能就收到了，或者已经写进去了
            print(f"[PLC] ⚠️ 无回执 (len={len(resp)})，但指令已发出")

    except Exception as e:
        print(f"[PLC] 写入异常: {e}")


if __name__ == "__main__":
    main()
