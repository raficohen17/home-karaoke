from karaoke.netinfo import parse_ifconfig, pick_lan_ip

IFCONFIG = """lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384
\tinet 127.0.0.1 netmask 0xff000000
en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500
\tether aa:bb:cc:dd:ee:ff
\tinet 192.168.1.23 netmask 0xffffff00 broadcast 192.168.1.255
utun4: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1400
\tinet 10.200.0.5 --> 10.200.0.5 netmask 0xffffffff
bridge100: flags=8863<UP> mtu 1500
\tinet 192.168.64.1 netmask 0xffffff00
"""


def test_parse_ifconfig():
    assert parse_ifconfig(IFCONFIG) == [
        ("lo0", "127.0.0.1"),
        ("en0", "192.168.1.23"),
        ("utun4", "10.200.0.5"),
        ("bridge100", "192.168.64.1"),
    ]


def test_pick_skips_vpn_and_bridges():
    assert pick_lan_ip(parse_ifconfig(IFCONFIG)) == "192.168.1.23"


def test_pick_none_when_only_vpn():
    assert pick_lan_ip([("utun0", "10.0.0.2"), ("lo0", "127.0.0.1")]) is None


def test_pick_prefers_192_over_10_on_physical():
    assert pick_lan_ip([("en1", "10.0.0.4"), ("en0", "192.168.0.9")]) == "192.168.0.9"
