import socket
import sys

target_ip = "12.42.7.135"
# 常见 Modbus TCP 及工业协议端口
common_ports = [502, 503, 5020, 8000, 8080, 102, 44818, 2404]

print(f"正在扫描主机 {target_ip} 的常见端口...")

open_ports = []

for port in common_ports:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    result = sock.connect_ex((target_ip, port))
    if result == 0:
        print(f"✅ 端口 {port} 是开放的")
        open_ports.append(port)
    else:
        # print(f"   端口 {port} 关闭 (Code: {result})")
        pass
    sock.close()

if not open_ports:
    print("❌ 未发现开放的常见端口。")
    print("请检查：")
    print("1. RTU 设备是否已开启 Modbus TCP 服务？")
    print("2. 是否有防火墙限制？")
    print("3. 端口号是否被修改为非标准端口？")
else:
    print(f"发现开放端口: {open_ports}")

