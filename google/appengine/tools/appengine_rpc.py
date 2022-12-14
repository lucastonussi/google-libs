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
"""Tool for performing authenticated RPCs against App Engine."""

from __future__ import print_function

import gzip
import hashlib
import io
import logging
import os
import re
import socket
import sys
import time
import urllib

import google

from google.appengine._internal import six_subset






if six_subset.PY3:
  import http.cookiejar
  import urllib.error
  import urllib.request

  BaseHandler = urllib.request.BaseHandler
  HTTPError = urllib.error.HTTPError
  HTTPHandler = urllib.request.HTTPHandler
  HTTPDefaultErrorHandler = urllib.request.HTTPDefaultErrorHandler
  HTTPCookieProcessor = urllib.request.HTTPCookieProcessor
  HTTPSHandler = urllib.request.HTTPSHandler
  HTTPErrorProcessor = urllib.request.HTTPErrorProcessor
  MozillaCookieJar = http.cookiejar.MozillaCookieJar
  ProxyHandler = urllib.request.ProxyHandler
  LoadError = http.cookiejar.LoadError
  OpenerDirector = urllib.request.OpenerDirector
  Request = urllib.request.Request
  UnknownHandler = urllib.request.UnknownHandler
  addinfourl_fn = urllib.response.addinfourl
  urlencode_fn = urllib.parse.urlencode
else:
  import cookielib
  import fancy_urllib
  import urllib2

  BaseHandler = urllib2.BaseHandler
  HTTPError = urllib2.HTTPError
  HTTPHandler = urllib2.HTTPHandler
  HTTPSHandler = fancy_urllib.FancyHTTPSHandler
  HTTPDefaultErrorHandler = urllib2.HTTPDefaultErrorHandler
  HTTPCookieProcessor = urllib2.HTTPCookieProcessor
  HTTPErrorProcessor = urllib2.HTTPErrorProcessor
  ProxyHandler = fancy_urllib.FancyProxyHandler
  MozillaCookieJar = cookielib.MozillaCookieJar
  LoadError = cookielib.LoadError
  OpenerDirector = urllib2.OpenerDirector
  UnknownHandler = urllib2.UnknownHandler
  Request = fancy_urllib.FancyRequest
  addinfourl_fn = urllib2.addinfourl
  urlencode_fn = urllib.urlencode




try:
  import ssl
  _CAN_VALIDATE_CERTS = True
except ImportError:
  _CAN_VALIDATE_CERTS = False


def can_validate_certs():
  """Return True if we have the SSL package and can validate certificates."""
  return _CAN_VALIDATE_CERTS




def eprint(*args, **kwargs):
  """Print to stderr.

  Args:
    *args: Positional arguments to print.
    **kwargs: Keyword arguments to print.

  Returns:
    None
  """
  print(*args, file=sys.stderr, **kwargs)


logger = logging.getLogger('google.appengine.tools.appengine_rpc')

def GetPlatformToken(os_module=os, sys_module=sys, platform=sys.platform):
  """Returns a 'User-agent' token for the host system platform.

  Args:
    os_module, sys_module, platform: Used for testing.

  Returns:
    String containing the platform token for the host system.
  """
  if hasattr(sys_module, "getwindowsversion"):
    windows_version = sys_module.getwindowsversion()
    version_info = ".".join(str(i) for i in windows_version[:4])
    return platform + "/" + version_info
  elif hasattr(os_module, "uname"):
    uname = os_module.uname()
    return "%s/%s" % (uname[0], uname[2])
  else:
    return "unknown"

def HttpRequestToString(req, include_data=True):
  """Converts a urllib2.Request to a string.

  Args:
    req: urllib2.Request
  Returns:
    Multi-line string representing the request.
  """

  headers = ""
  for header in req.header_items():
    headers += "%s: %s\n" % (header[0], header[1])

  template = ("%(method)s %(selector)s %(type)s/1.1\n"
              "Host: %(host)s\n"
              "%(headers)s")
  if include_data:
    template = template + "\n%(data)s"

  req_selector = req.selector if hasattr(req, "selector") else req.get_selector
  if req_selector is None:
    req_selector = ""

  req_type = req.type if hasattr(req, "type") else req.get_type()
  if req_type is None:
    req_type = ""

  req_host = req.host if hasattr(req, "host") else req.get_host()
  if req_host is None:
    req_host = ""

  req_data = req.data if hasattr(req, "data") else req.get_data()
  if req_data is None:
    req_data = ""

  return template % {
      "method": req.get_method(),
      "selector": req_selector,
      "type": req_type.upper(),
      "host": req_host,
      "headers": headers,
      "data": repr(req_data),
  }


class ClientLoginError(HTTPError):
  """Raised to indicate there was an error authenticating with ClientLogin."""

  def __init__(self, url, code, msg, headers, args):
    HTTPError.__init__(self, url, code, msg, headers, None)
    self.args = args
    self._reason = args.get("Error")
    self.info = args.get("Info")

  def read(self):
    return '%d %s: %s' % (self.code, self.msg, self.reason)



  @property
  def reason(self):
    return self._reason


class AbstractRpcServer(object):
  """Provides a common interface for a simple RPC server."""


  RUNTIME = "python"

  def __init__(self, host, auth_function, user_agent, source,
               host_override=None, extra_headers=None, save_cookies=False,
               auth_tries=3, account_type=None, debug_data=True, secure=True,
               ignore_certs=False, rpc_tries=3, options=None):
    """Creates a new HttpRpcServer.

    Args:
      host: The host to send requests to.
      auth_function: A function that takes no arguments and returns an
        (email, password) tuple when called. Will be called if authentication
        is required.
      user_agent: The user-agent string to send to the server. Specify None to
        omit the user-agent header.
      source: The source to specify in authentication requests.
      host_override: The host header to send to the server (defaults to host).
      extra_headers: A dict of extra headers to append to every request. Values
        supplied here will override other default headers that are supplied.
      save_cookies: If True, save the authentication cookies to local disk.
        If False, use an in-memory cookiejar instead.  Subclasses must
        implement this functionality.  Defaults to False.
      auth_tries: The number of times to attempt auth_function before failing.
      account_type: One of GOOGLE, HOSTED_OR_GOOGLE, or None for automatic.
      debug_data: Whether debugging output should include data contents.
      secure: If the requests sent using Send should be sent over HTTPS.
      ignore_certs: If the certificate mismatches should be ignored.
      rpc_tries: The number of rpc retries upon http server error (i.e.
        Response code >= 500 and < 600) before failing.
      options: the command line options (ignored in this implementation).
    """
    if secure:
      self.scheme = "https"
    else:
      self.scheme = "http"
    self.ignore_certs = ignore_certs
    self.host = host
    self.host_override = host_override
    self.auth_function = auth_function
    self.source = source
    self.authenticated = False
    self.auth_tries = auth_tries
    self.debug_data = debug_data
    self.rpc_tries = rpc_tries


    self.account_type = account_type

    self.extra_headers = {}
    if user_agent:
      self.extra_headers["User-Agent"] = user_agent
    if extra_headers:
      self.extra_headers.update(extra_headers)

    self.save_cookies = save_cookies

    self.cookie_jar = MozillaCookieJar()
    self.opener = self._GetOpener()
    if self.host_override:
      logger.debug("Server: %s; Host: %s", self.host, self.host_override)
    else:
      logger.debug("Server: %s", self.host)


    if ((self.host_override and self.host_override == "localhost") or
        self.host == "localhost" or self.host.startswith("localhost:")):
      self._DevAppServerAuthenticate()

  def _GetOpener(self):
    """Returns an OpenerDirector for making HTTP requests.

    Returns:
      A urllib2.OpenerDirector object.
    """
    raise NotImplementedError

  def _CreateRequest(self, url, data=None):
    """Creates a new urllib request."""
    req = Request(url, data=data)
    if self.host_override:
      req.add_header("Host", self.host_override)
    for key, value in self.extra_headers.items():
      req.add_header(key, value)
    return req

  def _GetAuthToken(self, email, password):
    """Uses ClientLogin to authenticate the user, returning an auth token.

    Args:
      email:    The user's email address
      password: The user's password

    Raises:
      ClientLoginError: If there was an error authenticating with ClientLogin.
      HTTPError: If there was some other form of HTTP error.

    Returns:
      The authentication token returned by ClientLogin.
    """
    account_type = self.account_type
    if not account_type:

      if (self.host.split(':')[0].endswith(".google.com")
          or (self.host_override
              and self.host_override.split(':')[0].endswith(".google.com"))):

        account_type = "HOSTED_OR_GOOGLE"
      else:
        account_type = "GOOGLE"
    data = {
        "Email": email,
        "Passwd": password,
        "service": "ah",
        "source": self.source,
        "accountType": account_type
    }


    req = self._CreateRequest(
        url=("https://%s/accounts/ClientLogin" %
             os.getenv("APPENGINE_AUTH_SERVER", "www.google.com")),
        data=six_subset.ensure_binary(urlencode_fn(data)))
    try:
      response = self.opener.open(req)
      response_body = response.read()
      response_dict = dict(x.split(b"=")
                           for x in response_body.split(b"\n") if x)
      if os.getenv("APPENGINE_RPC_USE_SID", "0") == "1":
        self.extra_headers["Cookie"] = (
            "SID=%s; Path=/;" % response_dict[b"SID"])
      return six_subset.ensure_str(response_dict[b"Auth"])
    except HTTPError as e:
      if e.code == 403:
        body = e.read()
        response_dict = dict(x.split("=", 1) for x in body.split("\n") if x)
        raise ClientLoginError(req.get_full_url(), e.code, e.msg,
                               e.headers, response_dict)
      else:
        raise

  def _GetAuthCookie(self, auth_token):
    """Fetches authentication cookies for an authentication token.

    Args:
      auth_token: The authentication token returned by ClientLogin.

    Raises:
      HTTPError: If there was an error fetching the authentication cookies.
    """

    continue_location = "http://localhost/"
    args = {"continue": continue_location, "auth": auth_token}
    login_path = os.environ.get("APPCFG_LOGIN_PATH", "/_ah")
    req = self._CreateRequest("%s://%s%s/login?%s" %
                              (self.scheme, self.host, login_path,
                               urlencode_fn(args)))
    try:
      response = self.opener.open(req)
    except HTTPError as e:
      response = e
    if (response.code != 302 or
        response.info()["location"] != continue_location):
      raise HTTPError(req.get_full_url(), response.code, response.msg,
                      response.headers, response.fp)
    self.authenticated = True

  def _Authenticate(self):
    """Authenticates the user.

    The authentication process works as follows:
     1) We get a username and password from the user
     2) We use ClientLogin to obtain an AUTH token for the user
        (see http://code.google.com/apis/accounts/AuthForInstalledApps.html).
     3) We pass the auth token to /_ah/login on the server to obtain an
        authentication cookie. If login was successful, it tries to redirect
        us to the URL we provided.

    If we attempt to access the upload API without first obtaining an
    authentication cookie, it returns a 401 response and directs us to
    authenticate ourselves with ClientLogin.
    """
    for unused_i in range(self.auth_tries):
      credentials = self.auth_function()
      try:
        auth_token = self._GetAuthToken(credentials[0], credentials[1])
        if os.getenv("APPENGINE_RPC_USE_SID", "0") == "1":
          return
      except ClientLoginError as e:


        if e.reason == "CaptchaRequired":
          eprint("Please go to\n"
                 "https://www.google.com/accounts/DisplayUnlockCaptcha\n"
                 "and verify you are a human.  Then try again.")
          break
        if e.reason == "NotVerified":
          eprint("Account not verified.")
          break
        if e.reason == "TermsNotAgreed":
          eprint("User has not agreed to TOS.")
          break
        if e.reason == "AccountDeleted":
          eprint("The user account has been deleted.")
          break
        if e.reason == "AccountDisabled":
          eprint("The user account has been disabled.")
          break
        if e.reason == "ServiceDisabled":
          eprint("The user's access to the service has been "
                 "disabled.")
          break
        if e.reason == "ServiceUnavailable":
          eprint("The service is not available; try again later.")
          break
        raise
      self._GetAuthCookie(auth_token)
      return


  @staticmethod
  def _CreateDevAppServerCookieData(email, admin):
    """Creates cookie payload data.

    Args:
      email: The user's email address.
      admin: True if the user is an admin; False otherwise.

    Returns:
      String containing the cookie payload.
    """
    if email:
      user_id_digest = hashlib.md5(
          six_subset.ensure_binary(email.lower())).digest()
      user_id = "1" + "".join(
          ["%02d" % x for x in six_subset.iterbytes(user_id_digest)])[:20]
    else:
      user_id = ""
    return "%s:%s:%s" % (email, bool(admin), user_id)

  def _DevAppServerAuthenticate(self):
    """Authenticates the user on the dev_appserver."""
    credentials = self.auth_function()
    value = self._CreateDevAppServerCookieData(credentials[0], True)
    self.extra_headers["Cookie"] = ('dev_appserver_login="%s"; Path=/;' % value)

  def Send(self, request_path, payload=b"",
           content_type="application/octet-stream",
           timeout=None,
           **kwargs):
    """Sends an RPC and returns the response.

    Args:
      request_path: The path to send the request to, eg /api/appversion/create.
      payload: The body of the request, or None to send an empty request.
      content_type: The Content-Type header to use.
      timeout: timeout in seconds; default None i.e. no timeout.
        (Note: for large requests on OS X, the timeout doesn't work right.)
      kwargs: Any keyword arguments are converted into query string parameters.

    Returns:
      The response body, as a string.
    """
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
      tries = 0
      auth_tried = False
      while True:
        tries += 1
        url = "%s://%s%s" % (self.scheme, self.host, request_path)
        if kwargs:


          url += "?" + urlencode_fn(sorted(kwargs.items()))
        req = self._CreateRequest(url=url, data=payload)
        req.add_header("Content-Type", content_type)



        req.add_header("X-appcfg-api-version", "1")

        try:
          logger.debug("Sending %s request:\n%s",
                       self.scheme.upper(),
                       HttpRequestToString(req, include_data=self.debug_data))
          f = self.opener.open(req)
          response = f.read()
          f.close()

          return response
        except HTTPError as e:
          logger.debug("Got http error, this is try %d: %s", tries, e)


          if tries > self.rpc_tries:
            raise
          elif e.code == 401:

            if auth_tried:
              raise
            auth_tried = True
            self._Authenticate()
          elif e.code >= 500 and e.code < 600:

            continue
          elif e.code == 302:


            if auth_tried:
              raise
            auth_tried = True
            loc = e.info()["location"]
            logger.debug("Got 302 redirect. Location: %s", loc)
            if loc.startswith("https://www.google.com/accounts/ServiceLogin"):
              self._Authenticate()
            elif re.match(
                r"https://www\.google\.com/a/[a-z0-9\.\-]+/ServiceLogin", loc):
              self.account_type = os.getenv("APPENGINE_RPC_HOSTED_LOGIN_TYPE",
                                            "HOSTED")
              self._Authenticate()
            elif loc.startswith("http://%s/_ah/login" % (self.host,)):
              self._DevAppServerAuthenticate()
            else:
              raise
          else:
            raise
    finally:
      socket.setdefaulttimeout(old_timeout)


class ContentEncodingHandler(BaseHandler):
  """Request and handle HTTP Content-Encoding."""

  def http_request(self, request):

    request.add_header("Accept-Encoding", "gzip")












    for header in request.headers:
      if header.lower() == "user-agent":
        request.headers[header] += " gzip"

    return request

  https_request = http_request

  def http_response(self, req, resp):
    """Handle encodings in the order that they are encountered."""
    encodings = []
    headers = resp.headers

    encoding_header = None
    for header in headers:
      if header.lower() == "content-encoding":
        encoding_header = header
        for encoding in headers[header].split(","):
          encoding = encoding.strip()
          if encoding:
            encodings.append(encoding)
        break

    if not encodings:
      return resp



    del headers[encoding_header]

    fp = resp
    while encodings and encodings[-1].lower() == "gzip":
      fp = io.BytesIO(fp.read())
      fp = gzip.GzipFile(fileobj=fp, mode="r")
      encodings.pop()

    if encodings:




      headers[encoding_header] = ", ".join(encodings)
      logger.warning("Unrecognized Content-Encoding: %s", encodings[-1])

    msg = resp.msg
    if sys.version_info >= (2, 6):
      resp = addinfourl_fn(fp, headers, resp.url, resp.code)
    else:
      response_code = resp.code
      resp = addinfourl_fn(fp, headers, resp.url)
      resp.code = response_code
    resp.msg = msg

    return resp

  https_response = http_response


class HttpRpcServer(AbstractRpcServer):
  """Provides a simplified RPC-style interface for HTTP requests."""

  DEFAULT_COOKIE_FILE_PATH = "~/.appcfg_cookies"

  def __init__(self, *args, **kwargs):
    self.certpath = os.path.normpath(os.path.join(
        os.path.dirname(__file__), '..', '..', '..', 'lib', 'cacerts',
        'cacerts.txt'))
    self.cert_file_available = ((not kwargs.get("ignore_certs", False))
                                and os.path.exists(self.certpath))
    super(HttpRpcServer, self).__init__(*args, **kwargs)

  def _CreateRequest(self, url, data=None):
    """Creates a new urllib request."""
    req = super(HttpRpcServer, self)._CreateRequest(url, data)
    if self.cert_file_available and can_validate_certs():
      req.set_ssl_info(ca_certs=self.certpath)
    return req

  def _CheckCookie(self):
    """Warn if cookie is not valid for at least one minute."""
    min_expire = time.time() + 60

    for cookie in self.cookie_jar:
      if cookie.domain == self.host and not cookie.is_expired(min_expire):
        break
    else:
      eprint("\nError: Machine system clock is incorrect.\n")


  def _Authenticate(self):
    """Save the cookie jar after authentication."""
    if self.cert_file_available and not can_validate_certs():


      logger.warning("""ssl module not found.
Without the ssl module, the identity of the remote host cannot be verified, and
connections may NOT be secure. To fix this, please install the ssl module from
http://pypi.python.org/pypi/ssl .
To learn more, see https://developers.google.com/appengine/kb/general#rpcssl""")
    super(HttpRpcServer, self)._Authenticate()
    if self.cookie_jar.filename is not None and self.save_cookies:
      logger.debug("Saving authentication cookies to %s",
                   self.cookie_jar.filename)
      self.cookie_jar.save()
      self._CheckCookie()

  def _GetOpener(self):
    """Returns an OpenerDirector that supports cookies and ignores redirects.

    Returns:
      A urllib2.OpenerDirector object.
    """
    opener = OpenerDirector()
    opener.add_handler(ProxyHandler())
    opener.add_handler(UnknownHandler())
    opener.add_handler(HTTPHandler())
    opener.add_handler(HTTPDefaultErrorHandler())
    opener.add_handler(HTTPSHandler())
    opener.add_handler(HTTPErrorProcessor())
    opener.add_handler(ContentEncodingHandler())

    if self.save_cookies:
      self.cookie_jar.filename = os.path.expanduser(
          HttpRpcServer.DEFAULT_COOKIE_FILE_PATH)

      if os.path.exists(self.cookie_jar.filename):
        try:
          self.cookie_jar.load()
          self.authenticated = True
          logger.debug("Loaded authentication cookies from %s",
                       self.cookie_jar.filename)
        except (OSError, IOError, LoadError) as e:

          logger.debug("Could not load authentication cookies; %s: %s",
                       e.__class__.__name__, e)
          self.cookie_jar.filename = None
      else:


        try:
          fd = os.open(self.cookie_jar.filename, os.O_CREAT, 0o600)
          os.close(fd)
        except (OSError, IOError) as e:

          logger.debug("Could not create authentication cookies file; %s: %s",
                       e.__class__.__name__, e)
          self.cookie_jar.filename = None

    opener.add_handler(HTTPCookieProcessor(self.cookie_jar))
    return opener
