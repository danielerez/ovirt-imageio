# ovirt-imageio-common
# Copyright (C) 2015-2016 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from __future__ import absolute_import

import socket
import time

from contextlib import closing

from ovirt_imageio_common import nbd

from . import testutil


def test_wait_for_unix_socket(tmpdir):
    addr = nbd.UnixAddress(tmpdir.join("path"))

    # Socket was not created yet.
    start = time.time()
    assert not testutil.wait_for_socket(addr, 0.1)
    waited = time.time() - start
    assert 0.1 <= waited < 0.2

    sock = socket.socket(socket.AF_UNIX)
    with closing(sock):
        sock.bind(addr)

        # Socket bound but not listening yet.
        start = time.time()
        assert not testutil.wait_for_socket(addr, 0.1)
        waited = time.time() - start
        assert 0.1 <= waited < 0.2

        sock.listen(1)

        # Socket listening - should return immediately.
        assert testutil.wait_for_socket(addr, 0.0)

    # Socket was closed - should return immediately.
    assert not testutil.wait_for_socket(addr, 0.0)


def test_wait_for_tcp_socket():
    sock = socket.socket()
    with closing(sock):
        sock.bind(("localhost", 0))
        addr = nbd.TCPAddress(*sock.getsockname())

        # Socket bound but not listening yet.
        start = time.time()
        assert not testutil.wait_for_socket(addr, 0.1)
        waited = time.time() - start
        assert 0.1 <= waited < 0.2

        sock.listen(1)

        # Socket listening - should return immediately.
        assert testutil.wait_for_socket(addr, 0.0)

    # Socket was closed - should return immediately.
    assert not testutil.wait_for_socket(addr, 0.0)


def test_random_tcp_port():
    # Use 100 iterations to detect flakyness early.
    for i in range(100):
        s = socket.socket()
        with closing(s):
            port = testutil.random_tcp_port()
            s.bind(("localhost", port))
