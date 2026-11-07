"""简易本地静态服务器：python server.py [端口]（默认 8080）
监听 0.0.0.0，同一局域网的其他设备可通过本机 IP 访问。"""
import socket
import sys
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
ROOT = Path(__file__).resolve().parent


def lan_ip():
    """获取本机局域网 IP（不实际发包）"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
server = ThreadingHTTPServer(("0.0.0.0", PORT), handler)
print(f"计时器已启动：")
print(f"  本机访问：  http://localhost:{PORT}")
print(f"  局域网访问：http://{lan_ip()}:{PORT}")
server.serve_forever()
