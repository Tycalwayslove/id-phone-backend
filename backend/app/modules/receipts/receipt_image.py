"""从服务商回调提供的地址下载回执图片。"""

import http.client
import io
import socket
import ssl
from ipaddress import ip_address
from urllib.parse import urlsplit

from PIL import Image

_MAX_BYTES = 10 * 1024 * 1024
_MAX_PIXELS = 25_000_000
_TIMEOUT = 5
_FORMATS = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png")}


class _ReceiptImageConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str) -> None:
        self._address = address
        self._tls = ssl.create_default_context()
        super().__init__(host, port=443, timeout=_TIMEOUT, context=self._tls)

    def connect(self) -> None:
        # 使用已校验的 IP，TLS 仍按 URL 中的主机名校验证书。
        sock = socket.create_connection((self._address, 443), timeout=_TIMEOUT)
        try:
            self.sock = self._tls.wrap_socket(sock, server_hostname=self.host)
        except OSError:
            sock.close()
            raise


def _public_address(host: str) -> str:
    for _, _, _, _, endpoint in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        address = ip_address(endpoint[0])
        if address.is_global and not address.is_multicast and not getattr(address, "is_site_local", False):
            return str(address)
    raise ValueError("回执图片地址未解析到公网 IP")


def download(url: str) -> tuple[bytes, str, str]:
    """读取有大小上限的 HTTPS 图片，按实际格式返回字节、内容类型和扩展名。"""
    location = urlsplit(url)
    if (
        location.scheme != "https"
        or not location.hostname
        or location.port not in (None, 443)
        or location.username is not None
        or location.fragment
    ):
        raise ValueError("回执图片地址无效")
    host = location.hostname.encode("idna").decode("ascii")
    path = location.path or "/"
    if location.query:
        path += "?" + location.query

    conn = _ReceiptImageConnection(host, _public_address(host))
    try:
        conn.request("GET", path)
        with conn.getresponse() as response:
            if response.status != 200:
                raise ValueError("回执图片服务未返回图片")
            data = response.read(_MAX_BYTES + 1)
    finally:
        conn.close()

    if len(data) > _MAX_BYTES:
        raise ValueError("回执图片超过大小上限")
    with Image.open(io.BytesIO(data), formats=list(_FORMATS)) as image:
        if image.width * image.height > _MAX_PIXELS:
            raise ValueError("回执图片超过像素上限")
        mime, ext = _FORMATS[image.format]
        image.load()
    return data, mime, ext
