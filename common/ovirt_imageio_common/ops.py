# ovirt-imageio-daemon
# Copyright (C) 2015-2016 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from __future__ import absolute_import

import logging

from contextlib import closing

from . import compat
from . import errors
from . import util

# This value is used by vdsm when copying image data using dd. Smaller values
# save memory, and larger values minimize syscall and python calls overhead.
BUFFERSIZE = 1024 * 1024

log = logging.getLogger("ops")


class EOF(Exception):
    """ Raised when no more data is available and size was not specifed """


class Operation(object):

    def __init__(self, size=None, offset=0, buffersize=BUFFERSIZE,
                 clock=util.NullClock()):
        self._size = size
        self._offset = offset
        if self._size:
            self._buffersize = min(util.round_up(size, 4096), buffersize)
        else:
            self._buffersize = buffersize
        self._done = 0
        self._clock = clock

    @property
    def size(self):
        return self._size

    @property
    def offset(self):
        return self._offset

    @property
    def done(self):
        return self._done

    @property
    def _todo(self):
        if self._size is None:
            return self._buffersize
        return self._size - self._done

    def run(self):
        with self._clock.run("operation"):
            self._run()

    def __repr__(self):
        return ("<{self.__class__.__name__} "
                "size={self.size} offset={self._offset} "
                "buffersize={self._buffersize} done={self.done} "
                "at 0x{id}>").format(self=self, id=id(self))


class Send(Operation):
    """
    Send data source backend to file object.
    """

    def __init__(self, src, dst, size=None, offset=0, buffersize=BUFFERSIZE,
                 clock=util.NullClock()):
        super(Send, self).__init__(size=size, offset=offset,
                                   buffersize=buffersize, clock=clock)
        self._src = src
        self._dst = dst

    def _run(self):
        with closing(util.aligned_buffer(self._buffersize)) as buf:
            try:
                skip = self._offset % self._src.block_size
                self._src.seek(self._offset - skip)
                if skip:
                    self._send_chunk(buf, skip)
                while self._todo:
                    self._send_chunk(buf)
            except EOF:
                pass

    def _send_chunk(self, buf, skip=0):
        if self._src.tell() % self._src.block_size:
            if self._size is None:
                raise EOF
            raise errors.PartialContent(self.size, self.done)

        with self._clock.run("read"):
            count = self._src.readinto(buf)
        if count == 0:
            if self._size is None:
                raise EOF
            raise errors.PartialContent(self.size, self.done)

        size = min(count - skip, self._todo)
        with self._clock.run("write"):
            self._dst.write(compat.bufview(buf, skip, size))
        self._done += size


class Receive(Operation):
    """
    Receive data from file object to destination backend.
    """

    def __init__(self, dst, src, size=None, offset=0, flush=True,
                 buffersize=BUFFERSIZE, clock=util.NullClock()):
        super(Receive, self).__init__(size=size, offset=offset,
                                      buffersize=buffersize, clock=clock)
        self._src = src
        self._dst = dst
        self._flush = flush

    def _run(self):
        with closing(util.aligned_buffer(self._buffersize)) as buf:
            try:
                self._dst.seek(self._offset)

                # If offset is not aligned to block size, receive partial chunk
                # until the start of the next block.
                unaligned = self._offset % self._dst.block_size
                if unaligned:
                    count = min(self._todo, self._dst.block_size - unaligned)
                    self._receive_chunk(buf, count)

                # Now current file position is aligned to block size and we can
                # receive full chunks.
                while self._todo:
                    count = min(self._todo, self._buffersize)
                    self._receive_chunk(buf, count)
            except EOF:
                pass
            finally:
                if self._flush:
                    with self._clock.run("sync"):
                        self._dst.flush()

    def _receive_chunk(self, buf, count):
        buf.seek(0)
        toread = count
        while toread:
            with self._clock.run("read"):
                chunk = self._src.read(toread)
            if not chunk:
                break
            buf.write(chunk)
            toread -= len(chunk)

        towrite = buf.tell()
        while towrite:
            offset = buf.tell() - towrite
            size = buf.tell() - offset
            with self._clock.run("write"):
                written = self._dst.write(compat.bufview(buf, offset, size))
            towrite -= written

        self._done += buf.tell()
        if buf.tell() < count:
            if self._size is None:
                raise EOF
            raise errors.PartialContent(self.size, self.done)


class Zero(Operation):
    """
    Zero byte range.
    """

    def __init__(self, dst, size, offset=0, flush=False,
                 buffersize=BUFFERSIZE, clock=util.NullClock()):
        super(Zero, self).__init__(size=size, offset=offset,
                                   buffersize=buffersize, clock=clock)
        self._dst = dst
        self._flush = flush

    def _run(self):
        self._dst.seek(self._offset)

        while self._todo:
            # Use small steps so we update self._done regularly, and avoid
            # blocking in kernel for too long time. Zeroing 128 MiB take less
            # than 1 second on my poor LIO storage.
            step = min(self._todo, 128 * 1024**2)
            with self._clock.run("zero"):
                self._done += self._dst.zero(step)

        if self._flush:
            self.flush()

    def flush(self):
        with self._clock.run("flush"):
            self._dst.flush()


class Flush(Operation):
    """
    Flush received data to storage.
    """

    def __init__(self, dst, clock=util.NullClock()):
        super(Flush, self).__init__(clock=clock)
        self._dst = dst

    def _run(self):
        with self._clock.run("flush"):
            self._dst.flush()
