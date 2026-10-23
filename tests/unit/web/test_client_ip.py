"""client_ip 信任链测试：仅当直连对端是内网/回环地址时采信 XFF，并取最右一个不可信跳。"""
from __future__ import annotations

from types import SimpleNamespace

from quickquip.app.web.client_ip import get_client_ip


def _request(host: str, xff: str | None = None):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers)


class TestDirectPeer:
    def test_public_direct_peer_ignores_xff(self):
        request = _request("9.9.9.9", xff="1.1.1.1")
        assert get_client_ip(request) == "9.9.9.9"

    def test_private_direct_peer_without_xff_returns_peer(self):
        assert get_client_ip(_request("10.0.0.1")) == "10.0.0.1"
        assert get_client_ip(_request("127.0.0.1")) == "127.0.0.1"

    def test_public_172_outside_rfc1918_is_not_trusted(self):
        # 172.16.0.0/12 以外的 172.x 是公网地址，不得进入 XFF 信任分支
        request = _request("172.15.0.1", xff="1.1.1.1")
        assert get_client_ip(request) == "172.15.0.1"

    def test_172_16_boundary(self):
        assert get_client_ip(_request("172.16.0.1", xff="8.8.8.8")) == "8.8.8.8"
        assert get_client_ip(_request("172.31.255.254", xff="8.8.8.8")) == "8.8.8.8"
        assert get_client_ip(_request("172.32.0.1", xff="8.8.8.8")) == "172.32.0.1"

    def test_loopback_v6_trusted(self):
        assert get_client_ip(_request("::1", xff="8.8.8.8")) == "8.8.8.8"


class TestXffChain:
    def test_overwrite_semantics_single_hop(self):
        assert get_client_ip(_request("10.0.0.1", xff="8.8.8.8")) == "8.8.8.8"

    def test_append_semantics_takes_real_client_not_spoofed_left(self):
        # $proxy_add_x_forwarded_for 形态：客户端伪造值在左，nginx 追加的真实对端在右
        request = _request("10.0.0.1", xff="1.2.3.4, 8.8.8.8")
        assert get_client_ip(request) == "8.8.8.8"

    def test_skips_trusted_hops_from_right(self):
        # 链尾是内网代理时继续向左找第一个公网跳
        request = _request("10.0.0.1", xff="8.8.8.8, 172.18.0.2")
        assert get_client_ip(request) == "8.8.8.8"

    def test_all_hops_trusted_falls_back_to_direct_peer(self):
        request = _request("10.0.0.1", xff="192.168.1.2, 172.18.0.2")
        assert get_client_ip(request) == "10.0.0.1"

    def test_blank_and_garbled_hops_skipped_or_returned_verbatim(self):
        # 空跳被跳过；无法解析为 IP 的跳按不可信处理，原样作为限流键
        assert get_client_ip(_request("10.0.0.1", xff=" ")) == "10.0.0.1"
        assert get_client_ip(_request("10.0.0.1", xff="garbled, 8.8.8.8")) == "8.8.8.8"
        assert get_client_ip(_request("10.0.0.1", xff="garbled")) == "garbled"
