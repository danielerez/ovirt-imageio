# ovirt-imageio-daemon
# Copyright (C) 2015-2017 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from __future__ import absolute_import

import uuid


def create_ticket(uuid=str(uuid.uuid4()), ops=None, timeout=300, size=2**64,
                  url="file:///var/run/vdsm/storage/foo", transfer_id=None,
                  filename=None, sparse=None):
    d = {
        "uuid": uuid,
        "timeout": timeout,
        "ops": ["read", "write"] if ops is None else ops,
        "size": size,
        "url": url,
    }
    if transfer_id is not None:
        d["transfer_id"] = transfer_id
    if filename is not None:
        d["filename"] = filename
    if sparse is not None:
        d["sparse"] = sparse
    return d


def create_tempfile(tmpdir, name, data=b'', size=None):
    file = tmpdir.join(name)
    with open(str(file), 'wb') as f:
        if size is not None:
            f.truncate(size)
        if data:
            f.write(data)
    return file
