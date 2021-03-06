# ovirt-imageio
# Copyright (C) 2019 Red Hat, Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

from __future__ import absolute_import

import pytest
from six.moves import urllib_parse


class Backend(object):
    """
    Wrap a userstorage.Backend, adding a url and context manager interface to
    simplify fixtures.
    """

    def __init__(self, storage):
        if not storage.exists():
            pytest.xfail("Storage {} is not available".format(storage.name))

        self._storage = storage
        self.path = storage.path
        self.url = urllib_parse.urlparse("file:" + storage.path)
        self.sector_size = storage.sector_size

    def __enter__(self):
        self._storage.setup()
        return self

    def __exit__(self, *args):
        self._storage.teardown()
