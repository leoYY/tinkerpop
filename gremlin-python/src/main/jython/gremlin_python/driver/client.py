"""
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""
import collections
import functools

from concurrent.futures import ThreadPoolExecutor

from six.moves import queue

from gremlin_python.driver import connection, protocol, request
from gremlin_python.process import traversal

# This is until concurrent.futures backport 3.1.0 release
try:
    from multiprocessing import cpu_count
except ImportError:
    # some platforms don't have multiprocessing
    def cpu_count():
        return None


class Client:

    def __init__(self, url, traversal_source, protocol_factory=None,
                 transport_factory=None, pool_size=None, max_workers=None,
                 username="", password=""):
        self._url = url
        self._traversal_source = traversal_source
        self._username = username
        self._password = password
        if transport_factory is None:
            try:
                from gremlin_python.driver.tornado.transport import (
                    TornadoTransport)
            except ImportError:
                raise Exception("Please install Tornado or pass"
                                "custom transport factory")
            else:
                transport_factory = lambda: TornadoTransport()
        self._transport_factory = transport_factory
        if protocol_factory is None:
            protocol_factory = lambda: protocol.GremlinServerWSProtocol()
        self._protocol_factory = protocol_factory
        if pool_size is None:
            pool_size = 4
        self._pool_size = pool_size
        # This is until concurrent.futures backport 3.1.0 release
        if max_workers is None:
            # Use this number because ThreadPoolExecutor is often
            # used to overlap I/O instead of CPU work.
            max_workers = (cpu_count() or 1) * 5
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        # Threadsafe queue
        self._pool = queue.Queue()
        self._fill_pool()

    @property
    def executor(self):
        return self._executor

    @property
    def traversal_source(self):
        return self._traversal_source

    def _fill_pool(self):
        for i in range(self._pool_size):
            conn = self._get_connection()
            self._pool.put_nowait(conn)

    def close(self):
        while not self._pool.empty():
            conn = self._pool.get(True)
            conn.close()
        self._executor.shutdown()

    def _get_connection(self):
        protocol = self._protocol_factory()
        return connection.Connection(
            self._url, self._traversal_source, protocol,
            self._transport_factory, self._executor, self._pool,
            self._username, self._password)

    def submit(self, message):
        return self.submitAsync(message).result()

    def submitAsync(self, message):
        if isinstance(message, traversal.Bytecode):
            message = request.RequestMessage(
                processor='traversal', op='bytecode',
                args={'gremlin': message,
                      'aliases': {'g': self._traversal_source}})
        conn = self._pool.get(True)
        return conn.write(message)