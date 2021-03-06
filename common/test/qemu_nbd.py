# ovirt-imageio
# Copyright (C) 2018 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from __future__ import absolute_import

import logging
from contextlib import contextmanager

from six.moves import urllib_parse

from ovirt_imageio_common import nbd
from ovirt_imageio_common.compat import subprocess

from . import testutil

log = logging.getLogger("qemu_nbd")


class Server(object):

    def __init__(self, image, fmt, sock, export_name="", read_only=False,
                 timeout=1.0):
        self.image = image
        self.fmt = fmt
        self.sock = sock
        self.export_name = export_name
        self.read_only = read_only
        self.timeout = timeout
        self.proc = None

    @property
    def url(self):
        url = self.sock.url(self.export_name)
        return urllib_parse.urlparse(url)

    def start(self):
        cmd = [
            "qemu-nbd",
            "--format", self.fmt,
            "--export-name", self.export_name.encode("utf-8"),
            "--persistent",
            "--cache=none",
            "--aio=native",
            "--discard=unmap",
        ]

        if self.sock.transport == "unix":
            cmd.append("--socket=%s" % self.sock.path)
        elif self.sock.transport == "tcp":
            cmd.append("--bind=%s" % self.sock.host)
            cmd.append("--port=%s" % self.sock.port)
        else:
            raise RuntimeError("Unsupported transport: {}".format(self.sock))

        if self.read_only:
            cmd.append("--read-only")

        cmd.append(self.image)

        log.debug("Starting qemu-nbd %s", cmd)
        self.proc = subprocess.Popen(cmd)

        if not testutil.wait_for_socket(self.sock, self.timeout):
            self.stop()
            raise RuntimeError("Timeout waiting for qemu-nbd socket")

        log.debug("qemu-nbd socket ready")

    def stop(self):
        if self.proc:
            log.debug("Terminating qemu-nbd gracefully")
            self.proc.terminate()
            try:
                self.proc.wait(1)
            except subprocess.TimeoutExpired:
                log.warning("Timeout terminating qemu-nbd - killing it")
                self.proc.kill()
                self.proc.wait()
            log.debug("qemu-nbd terminated with exit code %s",
                      self.proc.returncode)
            self.proc = None


@contextmanager
def run(image, fmt, sock, export_name="", read_only=False):
    server = Server(
        image, fmt, sock, export_name=export_name, read_only=read_only)
    server.start()
    try:
        yield
    finally:
        server.stop()


@contextmanager
def open(image, fmt, read_only=False):
    """
    Open nbd client for accessing image using qemu-nbd.
    """
    sock = nbd.UnixAddress(image + ".sock")
    with run(image, fmt, sock, read_only=read_only):
        with nbd.Client(sock) as c:
            yield c
