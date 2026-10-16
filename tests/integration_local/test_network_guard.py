"""Sensibilidade do bloqueio de rede da L2 (T08 · §10).

Se o bloqueio parar de funcionar, estes testes quebram — é o alarme
sintético do plano. Os dois caminhos cobertos são os usados na prática:
``socket.create_connection`` (chamadas diretas) e o ``connect`` cru da
classe (caminho de urllib3/requests via ``socket.socket``).
"""

import socket

import pytest

from tests.integration_local.conftest import NetworkBlockedError


def test_create_connection_is_blocked():
    with pytest.raises(NetworkBlockedError, match="rede bloqueada"):
        socket.create_connection(("127.0.0.1", 9), timeout=0.5)


def test_raw_socket_connect_is_blocked():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkBlockedError, match="rede bloqueada"):
            sock.connect(("127.0.0.1", 9))
    finally:
        sock.close()
