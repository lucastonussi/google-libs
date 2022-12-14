#!/usr/bin/env python
#
# Copyright 2007 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""A Python devappserver2 runtime."""



import importlib
import os
import sys
import time
import traceback

import google

if 'PYTHON_RUNTIME_EXTRA_IMPORTS' in os.environ:
  extras = os.environ['PYTHON_RUNTIME_EXTRA_IMPORTS'].split(':')
  for extra in extras:
    importlib.import_module(extra)
# pylint: disable=g-import-not-at-top

from google.appengine.api import rdbms_mysqldb
from google.appengine.ext.remote_api import remote_api_stub
from google.appengine.tools.devappserver2 import request_rewriter
from google.appengine.tools.devappserver2 import runtime_config_pb2
from google.appengine.tools.devappserver2 import wsgi_server
from google.appengine.tools.devappserver2.python import runtime
from google.appengine.tools.devappserver2.python.runtime import sandbox

_STARTUP_FAILURE_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<title>Startup Script Failure</title>
</head>

<body>
<b>Debugger startup failed: {exception_message}</b>
<details>
  <summary>Configuration</summary>
  <pre><code>{config}</code></pre>
</details>
<details>
  <summary>Traceback</summary>
  <pre><code>{traceback}</code></pre>
</details>
</body>
</html>"""


def setup_stubs(config):
  """Sets up API stubs using remote API.

  Args:
    config: a runtime_config.Config instance.
  """
  remote_api_stub.ConfigureRemoteApi(
      config.app_id,
      '/',
      lambda: ('', ''),
      '%s:%d' % (str(config.api_host), config.api_port),
      use_remote_datastore=False)

  if config.HasField('cloud_sql_config'):
    # Connect the RDBMS API to MySQL.
    sys.modules['google.appengine.api.rdbms'] = rdbms_mysqldb
    google.appengine.api.rdbms = rdbms_mysqldb

    connect_kwargs = dict(host=config.cloud_sql_config.mysql_host,
                          port=config.cloud_sql_config.mysql_port,
                          user=config.cloud_sql_config.mysql_user,
                          passwd=config.cloud_sql_config.mysql_password)

    if config.cloud_sql_config.mysql_socket:
      connect_kwargs['unix_socket'] = config.cloud_sql_config.mysql_socket
    elif (os.name == 'posix' and
          config.cloud_sql_config.mysql_host == 'localhost'):
      # From http://dev.mysql.com/doc/refman/5.0/en/connecting.html:
      # "On Unix, MySQL programs treat the host name localhost specially,
      # in a way that is likely different from what you expect compared to
      # other network-based programs. For connections to localhost, MySQL
      # programs attempt to connect to the local server by using a Unix socket
      # file. This occurs even if a --port or -P option is given to specify a
      # port number."
      #
      # This logic is duplicated in rdbms_mysqldb.connect but FindUnixSocket
      # will not worked in devappserver2 when rdbms_mysqldb.connect is called
      # because os.access is replaced in the sandboxed environment.
      #
      # A warning is not logged if FindUnixSocket returns None because it would
      # appear for all users, not just those who call connect.
      socket = rdbms_mysqldb.FindUnixSocket()
      # Don't set socket to None or the mysql driver will blow up with a
      # TypeError. This way it will raise a nicer connection error message.
      if socket is not None:
        connect_kwargs['unix_socket'] = socket

    rdbms_mysqldb.SetConnectKwargs(**connect_kwargs)


class StartupScriptFailureApplication(object):
  """A PEP-333 application that displays startup script failure information."""

  def __init__(self, config, exception_message, formatted_traceback):
    self._config = config
    self._exception_message = exception_message
    self._formatted_traceback = formatted_traceback

  def __call__(self, environ, start_response):
    start_response('500 Internal Server Error',
                   [('Content-Type', 'text/html')])
    yield _STARTUP_FAILURE_TEMPLATE.format(
        exception_message=self._exception_message,
        config=str(self._config),
        traceback=self._formatted_traceback)


class AutoFlush(object):
  def __init__(self, stream):
    self.stream = stream

  def write(self, data):
    self.stream.write(data)
    self.stream.flush()

  def __getattr__(self, attr):
    return getattr(self.stream, attr)


def expand_user(path):
  """Fake implementation of os.path.expanduser(path)."""
  return path


def main():
  # Required so PDB prompts work properly. Originally tried to disable buffering
  # (both by adding the -u flag when starting this process and by adding
  # "stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)" but neither worked).
  sys.stdout = AutoFlush(sys.stdout)
  assert len(sys.argv) == 3
  child_in_path = sys.argv[1]
  config = runtime_config_pb2.Config()
  config.ParseFromString(open(child_in_path, 'rb').read())
  os.remove(child_in_path)
  debugging_app = None
  if config.python_config and config.python_config.startup_script:
    global_vars = {'config': config}
    try:
      execfile(config.python_config.startup_script, global_vars)
    except Exception as e:
      debugging_app = StartupScriptFailureApplication(config,
                                                      str(e),
                                                      traceback.format_exc())

  # This line needs to be before enabling the sandbox because os.environ is
  # patched away.
  port = os.environ['PORT']
  if debugging_app:
    server = wsgi_server.WsgiServer(
        ('localhost', port),
        debugging_app)
  else:
    setup_stubs(config)
    sandbox.enable_sandbox(config)
    os.path.expanduser = expand_user
    # This import needs to be after enabling the sandbox so the runtime
    # implementation imports the sandboxed version of the logging module.
    # pylint: disable=g-import-not-at-top
    from google.appengine.tools.devappserver2.python.runtime import (
        request_handler)
    # pylint: enable=g-import-not-at-top
    server = wsgi_server.WsgiServer(
        ('localhost', port),
        request_rewriter.runtime_rewriter_middleware(
            request_handler.RequestHandler(config)))
  # Delete devappserver2.python.runtime and devappserver2.python.runtime.sandbox
  # from sys.modules so that future attempts to import
  # devappserver2.python.runtime.sandbox from user code goes through and gets
  # blocked by the sandbox's sys.meta_path import hooks.
  del sys.modules[sandbox.__name__]
  del sys.modules[runtime.__name__]
  server.start()
  try:
    while True:
      time.sleep(1)
  except KeyboardInterrupt:
    pass
  finally:
    server.quit()


if __name__ == '__main__':
  main()
