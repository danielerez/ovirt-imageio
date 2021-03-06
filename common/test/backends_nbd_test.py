# ovirt-imageio
# Copyright (C) 2018 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from __future__ import absolute_import

import io
from contextlib import closing

import pytest

from ovirt_imageio_common import util
from ovirt_imageio_common.backends import nbd
from ovirt_imageio_common.compat import subprocess


def test_debugging_interface(nbd_server):
    nbd_server.start()
    with nbd.open(nbd_server.url, "r+") as b:
        assert b.readable()
        assert b.writable()
        assert b.sparse
        assert b.name == "nbd"


def test_open_read_write(nbd_server):
    nbd_server.start()
    with nbd.open(nbd_server.url, "r+") as b:
        assert b.readable()
        assert b.writable()

        data = b"data"
        b.write(data)
        assert b.tell() == len(data)

        b.zero(4)
        size = len(data) + 4
        assert b.tell() == size

        with closing(util.aligned_buffer(size)) as buf:
            b.seek(0)
            assert b.readinto(buf) == size
            assert buf[:] == data + b"\0" * 4
        b.flush()


def test_open_read_larger_buffer(nbd_server):
    nbd_server.start()
    with nbd.open(nbd_server.url, "r") as b:
        # buffer larger than remaining data
        buffer_length = 10
        data_length = 5
        with closing(util.aligned_buffer(buffer_length)) as buf:
            b.seek(b._client.export_size - data_length)
            assert b.readinto(buf) == data_length
        b.flush()


def test_open_readonly(nbd_server):
    nbd_server.read_only = True
    nbd_server.start()
    with nbd.open(nbd_server.url, "r") as b:
        assert b.readable()
        assert not b.writable()

        with pytest.raises(IOError):
            b.write(b"data")
        assert b.tell() == 0

        with pytest.raises(IOError):
            b.zero(4)
        assert b.tell() == 0

        with closing(util.aligned_buffer(100)) as buf:
            buf.write(b"x" * 100)
            assert b.readinto(buf) == len(buf)
            assert buf[:] == b"\0" * len(buf)

        b.flush()


def test_open_writeonly(nbd_server):
    nbd_server.start()
    with nbd.open(nbd_server.url, "w") as b:
        assert not b.readable()
        assert b.writable()

        data = b"data"
        b.write(data)
        assert b.tell() == len(data)

        with pytest.raises(IOError):
            with closing(util.aligned_buffer(100)) as buf:
                b.readinto(buf)

        dst = io.BytesIO()
        with pytest.raises(IOError):
            b.write_to(dst, 100)

        b.flush()


def test_invalid_mode(nbd_server):
    nbd_server.start()
    with pytest.raises(ValueError):
        nbd.open(nbd_server.url, "invalid")


@pytest.mark.parametrize("buffer_size", [
    # Length aligned to buffer size.
    8 * 1024,
    # Length not aligned to buffer size.
    10 * 1024,
    # Length equal to buffer size.
    16 * 1024,
    # Length smaller than buffer size.
    20 * 1024,
])
def test_write_to_buffer_size(nbd_server, buffer_size):
    length = 16 * 1024

    with io.open(nbd_server.image, "wb") as f:
        f.truncate(length)
        for i in range(0, length, 1024):
            f.seek(i)
            f.write(b"%d\n" % i)

    nbd_server.start()

    dst = io.BytesIO()
    with nbd.open(nbd_server.url, "r", buffer_size=buffer_size) as b:
        n = b.write_to(dst, length)

        assert n == length
        assert b.tell() == length

    with io.open(nbd_server.image, "rb") as f:
        assert f.read() == dst.getvalue()


@pytest.mark.parametrize("length", [
    # Unalinged length, seems to be supported by qemu-nbg and qemu, always
    # publishing minimum_bloc_size = 1. However we tested only with files,
    # maybe with block device the minimum block size is higher?
    42,
    # Typical block sizes.
    512,
    4096,
    # The biggest read that can work by NBD spec.
    32 * 1024**2,
    # Will fail unless the backends implement a read loop.
    33 * 1024**2,
])
def test_write_to_length(nbd_server, length):
    # Create a sparse file for fastest reading.
    with io.open(nbd_server.image, "wb") as f:
        f.truncate(33 * 1024**2)

    nbd_server.start()

    dst = io.BytesIO()
    with nbd.open(nbd_server.url, "r") as b:
        n = b.write_to(dst, length)

        assert n == length
        assert b.tell() == length
        assert dst.tell() == length


@pytest.mark.parametrize("offset", [
    # Unalinged length.
    42,
    # Typical block sizes.
    512,
    4096,
    # Last block.
    16 * 1024 - 4096,
])
def test_write_to_offset(nbd_server, offset):
    with io.open(nbd_server.image, "wb") as f:
        f.truncate(16 * 1024)

    nbd_server.start()
    length = 4096

    dst = io.BytesIO()
    with nbd.open(nbd_server.url, "r") as b:
        b.seek(offset)
        n = b.write_to(dst, length)

        assert n == length
        assert b.tell() == offset + length
        assert dst.tell() == length


@pytest.mark.parametrize("sparse", [True, False])
def test_zero_middle(nbd_server, sparse):
    nbd_server.start()
    with nbd.open(nbd_server.url, "r+", sparse=sparse) as b:
        # nbd backend is always sparse.
        assert b.sparse

        b.write(b"xxxxxxxxxxxx")
        b.seek(4)
        assert b.zero(4) == 4

        with closing(util.aligned_buffer(12)) as buf:
            b.seek(0)
            assert b.readinto(buf) == 12
            assert buf[:] == b"xxxx\x00\x00\x00\x00xxxx"


def test_close(nbd_server):
    nbd_server.start()
    with nbd.open(nbd_server.url, "r+") as b:
        pass

    # Closing twice does not do anything.
    b.close()

    # But other operations should fail now with:
    #     socket.error: Bad file descriptor
    with pytest.raises(IOError):
        b.write("more")
    with pytest.raises(IOError):
        with closing(util.aligned_buffer(100)) as buf:
            b.readinto(buf)


def test_context_manager(nbd_server):
    nbd_server.start()
    with nbd.open(nbd_server.url, "r+") as b:
        b.write(b"data")
    with pytest.raises(IOError):
        b.write("more")


def test_dirty(nbd_server):
    nbd_server.start()
    with nbd.open(nbd_server.url, "r+") as b:
        # backend created clean
        assert not b.dirty

        # write and zero dirty the backend
        b.write(b"01234")
        assert b.dirty

        b.flush()
        assert not b.dirty

        b.zero(5)
        assert b.dirty

        b.flush()
        assert not b.dirty

        # readinto, seek do not affect dirty.
        b.seek(0)
        assert not b.dirty

        with closing(util.aligned_buffer(10)) as buf:
            b.readinto(buf)
        assert not b.dirty


@pytest.mark.parametrize("fmt", ["raw", "qcow2"])
def test_size(nbd_server, fmt):
    nbd_server.fmt = fmt
    subprocess.check_call(["qemu-img", "create", "-f",
                           fmt, nbd_server.image, "150m"])
    nbd_server.start()
    with nbd.open(nbd_server.url, "r") as b:
        assert b.size() == 150 * 1024**2
