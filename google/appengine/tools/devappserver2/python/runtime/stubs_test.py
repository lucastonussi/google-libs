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
"""Tests for google.appengine.tools.devappserver2.python.stubs."""



from distutils import util
import errno
import locale
import logging
import mimetypes
import os
import shutil
import sys
import tempfile
import unittest

import mock
import mox

# pylint: disable=g-import-not-at-top
# pylint: disable=g-bad-import-order
import e2e_test_paths

e2e_test_paths.RemoteGoogleModules()
e2e_test_paths.SetPathToDevappserverE2E()
os.environ['PYTHONPATH'] = os.pathsep.join(sys.path)

from google.appengine.tools.devappserver2.python.runtime import stubs


class StubsTest(unittest.TestCase):

  def setUp(self):
    super(StubsTest, self).setUp()
    self.platform = sys.platform
    self.mox = mox.Mox()
    self.mox.StubOutWithMock(locale, 'setlocale')
    self.mox.StubOutWithMock(util, 'get_platform')
    self.mox.StubOutWithMock(stubs.FakeFile, 'is_file_accessible')
    self.mox.StubOutWithMock(logging, 'info')

  def tearDown(self):
    self.mox.UnsetStubs()
    sys.platform = self.platform
    super(StubsTest, self).tearDown()

  def test_os_error_not_implemented(self):
    with self.assertRaises(OSError) as cm:
      stubs.os_error_not_implemented()
    self.mox.VerifyAll()
    e = cm.exception
    self.assertEqual(errno.ENOSYS, e.errno)
    self.assertEqual('Function not implemented', e.strerror)
    self.assertIsNone(e.filename)

  def test_return_minus_one(self):
    self.assertEqual(-1, stubs.return_minus_one())

  def test_fake_uname(self):
    self.assertEqual(('Linux', '', '', '', ''), stubs.fake_uname())

  def test_fake_listdir_in(self):
    my_dir = os.path.dirname(os.path.abspath(__file__))
    stubs.FakeFile.is_file_accessible(my_dir, False).AndReturn(
        stubs.FakeFile.Visibility.OK)
    for f in os.listdir(my_dir):
      p = os.path.join(my_dir, f)
      stubs.FakeFile.is_file_accessible(p).AndReturn(
          stubs.FakeFile.Visibility.OK)
    self.mox.ReplayAll()
    fake_listdir = stubs.make_fake_listdir(os.listdir)
    files = fake_listdir(my_dir)
    self.assertIn(os.path.basename(__file__), files)
    self.mox.VerifyAll()

  def test_fake_listdir_out(self):
    my_dir = os.path.dirname(os.path.abspath(__file__))
    stubs.FakeFile.is_file_accessible(my_dir, False).AndReturn(
        stubs.FakeFile.Visibility.OK)
    for f in os.listdir(my_dir):
      p = os.path.join(my_dir, f)
      if p != os.path.abspath(__file__):
        stubs.FakeFile.is_file_accessible(p).AndReturn(
            stubs.FakeFile.Visibility.OK)
      else:
        stubs.FakeFile.is_file_accessible(p).AndReturn(
            stubs.FakeFile.Visibility.SKIP_BLOCK)
    self.mox.ReplayAll()
    fake_listdir = stubs.make_fake_listdir(os.listdir)
    files = fake_listdir(my_dir)
    self.assertNotIn(os.path.basename(__file__), files)
    self.mox.VerifyAll()

  def test_fake_access_accessible(self):
    stubs.FakeFile.is_file_accessible(__file__, 0).AndReturn(
        stubs.FakeFile.Visibility.OK)
    self.mox.ReplayAll()
    self.assertTrue(stubs.fake_access(__file__, os.R_OK))
    self.mox.VerifyAll()

  def test_fake_access_inaccessible(self):
    stubs.FakeFile.is_file_accessible(__file__, 0).AndReturn(
        stubs.FakeFile.Visibility.SKIP_BLOCK)
    self.mox.ReplayAll()
    self.assertFalse(stubs.fake_access(__file__, os.R_OK))
    self.mox.VerifyAll()

  def test_fake_access_write(self):
    stubs.FakeFile.is_file_accessible(__file__, 2).AndReturn(
        stubs.FakeFile.Visibility.WRITE_BLOCK)
    self.mox.ReplayAll()
    self.assertFalse(stubs.fake_access(__file__, os.W_OK))
    self.mox.VerifyAll()

  def test_fake_open_accessible(self):
    stubs.FakeFile.is_file_accessible(__file__, 0).AndReturn(
        stubs.FakeFile.Visibility.OK)
    self.mox.ReplayAll()
    os.close(stubs.fake_open(__file__, os.O_RDONLY))
    self.mox.VerifyAll()

  def test_fake_open_inaccessible(self):
    stubs.FakeFile.is_file_accessible(__file__, 0).AndReturn(
        stubs.FakeFile.Visibility.STATIC_BLOCK)
    logging.info('Sandbox prevented access to static file "%s"', __file__)
    logging.info(
        'Check that `application_readable: true` is set in app.yaml')
    self.mox.ReplayAll()
    with self.assertRaises(OSError) as cm:
      stubs.fake_open(__file__, os.O_RDONLY)
    self.mox.VerifyAll()
    e = cm.exception
    self.assertEqual(errno.ENOENT, e.errno)
    self.assertEqual('No such file or directory', e.strerror)
    self.assertEqual(__file__, e.filename)
    self.mox.VerifyAll()

  def test_fake_open_write(self):
    stubs.FakeFile.is_file_accessible(__file__, 2).AndReturn(
        stubs.FakeFile.Visibility.WRITE_BLOCK)
    self.mox.ReplayAll()
    with self.assertRaises(OSError) as cm:
      stubs.fake_open(__file__, os.O_RDWR)
    self.mox.VerifyAll()
    e = cm.exception
    self.assertEqual(errno.EROFS, e.errno)
    self.assertEqual('Read-only file system', e.strerror)
    self.assertEqual(__file__, e.filename)
    self.mox.VerifyAll()

  def test_fake_set_locale_allowed(self):
    locale.setlocale(0, 'C')
    locale.setlocale(0, 'C')
    locale.setlocale(0, 'C')
    locale.setlocale(0, 'C')
    self.mox.ReplayAll()
    stubs.fake_set_locale(0, 'C', original_setlocale=locale.setlocale)
    stubs.fake_set_locale(0, None, original_setlocale=locale.setlocale)
    stubs.fake_set_locale(0, '', original_setlocale=locale.setlocale)
    stubs.fake_set_locale(0, 'POSIX', original_setlocale=locale.setlocale)
    self.mox.VerifyAll()

  def test_fake_set_locale_not_allowed(self):
    self.mox.ReplayAll()
    self.assertRaises(locale.Error, stubs.fake_set_locale, 0, 'AAAA')
    self.mox.VerifyAll()

  def test_fake_get_platform(self):
    sys.platform = 'linux2'
    self.mox.ReplayAll()
    self.assertEqual('linux-', stubs.fake_get_platform())
    self.mox.VerifyAll()

  def test_fake_get_platform_darwin(self):
    sys.platform = 'darwin'
    self.mox.ReplayAll()
    self.assertEqual('macosx-', stubs.fake_get_platform())
    self.mox.VerifyAll()

  def test_restricted_path_function_allowed(self):
    fake_function = self.mox.CreateMockAnything()
    fake_function('foo', bar='baz').AndReturn(1)
    stubs.FakeFile.is_file_accessible('foo', False).AndReturn(
        stubs.FakeFile.Visibility.OK)
    self.mox.ReplayAll()
    restricted_path_fake_function = stubs.RestrictedPathFunction(fake_function)
    self.assertEqual(1, restricted_path_fake_function('foo', bar='baz'))
    self.mox.VerifyAll()

  def test_static_access_message_restricted_path_function(self):
    fake_function = self.mox.CreateMockAnything()
    stubs.FakeFile.is_file_accessible('foo', False).AndReturn(
        stubs.FakeFile.Visibility.STATIC_BLOCK)
    logging.info('Sandbox prevented access to static file "%s"', 'foo')
    logging.info(
        'Check that `application_readable: true` is set in app.yaml')
    stubs.FakeFile.is_file_accessible('foo', False).AndReturn(
        stubs.FakeFile.Visibility.CACHED_BLOCK)
    self.mox.ReplayAll()
    # We'll try to access it twice here, the second time with the result cached.
    # Verify it only prints the message once.
    restricted_path_fake_function = stubs.RestrictedPathFunction(fake_function)
    with self.assertRaises(OSError) as cm:
      restricted_path_fake_function('foo', bar='baz')
    with self.assertRaises(OSError) as cm:
      restricted_path_fake_function('foo', bar='baz')
    self.mox.VerifyAll()
    e = cm.exception
    self.assertEqual(errno.EACCES, e.errno)
    self.assertEqual('path not accessible', e.strerror)
    self.assertEqual('foo', e.filename)


class FakeFileTest(unittest.TestCase):

  def setUp(self):
    super(FakeFileTest, self).setUp()
    self.mox = mox.Mox()
    self.tempdir = tempfile.mkdtemp()
    stubs.FakeFile._application_paths = []
    stubs.FakeFile.set_skip_files('^$')
    stubs.FakeFile.set_static_files('^$')

  def tearDown(self):
    stubs.FakeFile._application_paths = []
    self.mox.UnsetStubs()
    shutil.rmtree(self.tempdir)
    super(FakeFileTest, self).tearDown()

  def test_init_accessible(self):
    self.mox.StubOutWithMock(stubs.FakeFile, 'is_file_accessible')
    stubs.FakeFile.is_file_accessible(__file__, False).AndReturn(
        stubs.FakeFile.Visibility.OK)
    self.mox.ReplayAll()
    with stubs.FakeFile(__file__) as f:
      fake_file_content = f.read()
    self.mox.VerifyAll()
    with open(__file__) as f:
      real_file_content = f.read()
    self.assertEqual(real_file_content, fake_file_content)

  def test_init_inaccessible(self):
    self.mox.StubOutWithMock(stubs.FakeFile, 'is_file_accessible')
    stubs.FakeFile.is_file_accessible(__file__, False).AndReturn(
        stubs.FakeFile.Visibility.SKIP_BLOCK)
    self.mox.ReplayAll()
    self.assertRaises(IOError, stubs.FakeFile, __file__)
    self.mox.VerifyAll()

  def test_init_to_write(self):
    self.mox.StubOutWithMock(stubs.FakeFile, 'is_file_accessible')
    stubs.FakeFile.is_file_accessible(__file__, True).AndReturn(
        stubs.FakeFile.Visibility.WRITE_BLOCK)
    self.mox.ReplayAll()
    self.assertRaises(IOError, stubs.FakeFile, __file__, 'w')
    self.mox.VerifyAll()

  def test_init_to_append(self):
    self.mox.StubOutWithMock(stubs.FakeFile, 'is_file_accessible')
    stubs.FakeFile.is_file_accessible(__file__, True).AndReturn(
        stubs.FakeFile.Visibility.WRITE_BLOCK)
    self.mox.ReplayAll()
    self.assertRaises(IOError, stubs.FakeFile, __file__, 'a')
    self.mox.VerifyAll()

  def test_init_to_read_plus(self):
    self.mox.StubOutWithMock(stubs.FakeFile, 'is_file_accessible')
    stubs.FakeFile.is_file_accessible(__file__, True).AndReturn(
        stubs.FakeFile.Visibility.WRITE_BLOCK)
    self.mox.ReplayAll()
    self.assertRaises(IOError, stubs.FakeFile, __file__, 'r+')
    self.mox.VerifyAll()

  def test_is_accessible_accessible(self):
    open(os.path.join(self.tempdir, 'allowed'), 'w').close()
    stubs.FakeFile.set_allowed_paths(self.tempdir, [])
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'allowed')), stubs.FakeFile.Visibility.OK)

  def test_is_accessible_not_accessible(self):
    open(os.path.join(self.tempdir, 'not_allowed'), 'w').close()
    stubs.FakeFile.set_allowed_paths(os.path.join(self.tempdir, 'allowed'), [])
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'not_allowed')),
                     stubs.FakeFile.Visibility.PATH_BLOCK)

  def test_is_accessible_cache(self):
    open(os.path.join(self.tempdir, 'not_allowed'), 'w').close()
    stubs.FakeFile.set_allowed_paths(os.path.join(self.tempdir, 'allowed'), [])
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'not_allowed')),
                     stubs.FakeFile.Visibility.PATH_BLOCK)
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'not_allowed')),
                     stubs.FakeFile.Visibility.CACHED_BLOCK)

  def test_cache_write_then_read(self):
    # Accessibility rules for writing are stricter than for reading; check that
    # a failed attempt to open a read-only file for writing doesn't cache it as
    # "blocked" and prevent a subsequent attempt to open it for reading.
    filename = os.path.join(self.tempdir, 'allowed_for_read')
    open(filename, 'w').close()
    stubs.FakeFile.set_allowed_paths(filename, [])
    # The access test when opening for writing should fail.
    self.assertEqual(stubs.FakeFile.is_file_accessible(filename, True),
                     stubs.FakeFile.Visibility.WRITE_BLOCK)
    # The access test when opening for reading should succeed -- the previous
    # open-for-write test shouldn't result in a CACHED_BLOCK response here.
    self.assertEqual(stubs.FakeFile.is_file_accessible(filename),
                     stubs.FakeFile.Visibility.OK)

  def test_cache_read_then_write(self):
    # As for test_cache_write_then_read, except check that opening a read-only
    # file for reading doesn't result in it being cached as accessible for
    # writing.
    filename = os.path.join(self.tempdir, 'allowed_for_read')
    open(filename, 'w').close()
    stubs.FakeFile.set_allowed_paths(filename, [])
    # The access test when opening for reading should succeed.
    self.assertEqual(stubs.FakeFile.is_file_accessible(filename),
                     stubs.FakeFile.Visibility.OK)
    # The access test when opening for writing should fail -- the previous
    # open-for-read test shouldn't result in a cached OK response here.
    self.assertEqual(stubs.FakeFile.is_file_accessible(filename, True),
                     stubs.FakeFile.Visibility.WRITE_BLOCK)

  def test_allowed_write(self):
    # Ensure that writes to the allowed temporary folder will be permitted
    writeable_root = tempfile.mkdtemp()
    writeable_filename = os.path.join(writeable_root, 'allowed_for_write')
    readable_filename = os.path.join(self.tempdir, 'only_allowed_for_read')
    stubs.FakeFile.set_allowed_paths(self.tempdir, [], writeable_root)
    self.assertEqual(
        stubs.FakeFile.is_file_accessible(writeable_filename, True),
        stubs.FakeFile.Visibility.OK)
    self.assertEqual(
        stubs.FakeFile.is_file_accessible(readable_filename, True),
        stubs.FakeFile.Visibility.WRITE_BLOCK)
    self.assertEqual(
        stubs.FakeFile.is_file_accessible(readable_filename, False),
        stubs.FakeFile.Visibility.OK)

  def test_is_accessible_accessible_directory(self):
    os.mkdir(os.path.join(self.tempdir, 'allowed'))
    stubs.FakeFile.set_allowed_paths(self.tempdir, [])
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'allowed')), stubs.FakeFile.Visibility.OK)

  def test_is_accessible_not_accessible_directory(self):
    os.mkdir(os.path.join(self.tempdir, 'not_allowed'))
    stubs.FakeFile.set_allowed_paths(os.path.join(self.tempdir, 'allowed'), [])
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'not_allowed')),
                     stubs.FakeFile.Visibility.PATH_BLOCK)

  def test_is_accessible_accessible_in_application_dir(self):
    open(os.path.join(self.tempdir, 'allowed'), 'w').close()
    stubs.FakeFile.set_allowed_paths('.', [self.tempdir])
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'allowed')), stubs.FakeFile.Visibility.OK)

  def test_is_accessible_accessible_directory_in_application_dir(self):
    os.mkdir(os.path.join(self.tempdir, 'allowed'))
    stubs.FakeFile.set_allowed_paths('.', [self.tempdir])
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'allowed')), stubs.FakeFile.Visibility.OK)

  def test_is_accessible_mimetypes_files(self):
    stubs.FakeFile.set_allowed_paths(self.tempdir, [])
    for filename in mimetypes.knownfiles:
      if os.path.isfile(filename):
        self.assertEqual(stubs.FakeFile.is_file_accessible(filename),
                         stubs.FakeFile.Visibility.OK)

  def test_is_accessible_skipped(self):
    open(os.path.join(self.tempdir, 'allowed'), 'w').close()
    stubs.FakeFile.set_allowed_paths(self.tempdir, [])
    stubs.FakeFile.set_skip_files('^%s$' % 'allowed')
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'allowed')),
                     stubs.FakeFile.Visibility.SKIP_BLOCK)

  def test_is_accessible_skipped_root_appdir(self):
    stubs.FakeFile.set_allowed_paths(self.tempdir, [])
    stubs.FakeFile.set_skip_files(r'^(\..*)|$')
    self.assertEqual(stubs.FakeFile.is_file_accessible(self.tempdir),
                     stubs.FakeFile.Visibility.OK)

  def test_is_accessible_skipped_root_appdir_with_trailing_slash(self):
    stubs.FakeFile.set_allowed_paths(self.tempdir, [])
    stubs.FakeFile.set_skip_files(r'^(\..*)|$')
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        '%s%s' % (self.tempdir, os.path.sep)), stubs.FakeFile.Visibility.OK)

  def test_is_accessible_skipped_and_not_accessible(self):
    stubs.FakeFile.set_allowed_paths(os.path.join(self.tempdir, 'allowed'), [])
    stubs.FakeFile.set_skip_files('^.*%s.*$' % 'not_allowed')
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'not_allowed')),
                     stubs.FakeFile.Visibility.PATH_BLOCK)

  def test_is_accessible_skipped_outside_appdir(self):
    stubs.FakeFile.set_allowed_paths(os.path.join(self.tempdir, 'foo'),
                                     [os.path.join(self.tempdir, 'allowed')])
    stubs.FakeFile.set_skip_files('^.*%s.*$' % 'filename')
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'allowed', 'filename')),
                     stubs.FakeFile.Visibility.OK)

  def test_is_accessible_static(self):
    open(os.path.join(self.tempdir, 'allowed'), 'w').close()
    stubs.FakeFile.set_allowed_paths(self.tempdir, [])
    stubs.FakeFile.set_static_files('^%s$' % 'allowed')
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'allowed')),
                     stubs.FakeFile.Visibility.STATIC_BLOCK)

  def test_is_accessible_static_and_not_accessible(self):
    stubs.FakeFile.set_allowed_paths(os.path.join(self.tempdir, 'allowed'), [])
    stubs.FakeFile.set_static_files('^.*%s.*$' % 'not_allowed')
    self.assertEqual(stubs.FakeFile.is_file_accessible(
        os.path.join(self.tempdir, 'not_allowed')),
                     stubs.FakeFile.Visibility.PATH_BLOCK)

  def test_is_accessible_skipped_and_static_root_appdir(self):
    stubs.FakeFile.set_allowed_paths(self.tempdir, [])
    self.assertEqual(stubs.FakeFile.is_file_accessible(self.tempdir),
                     stubs.FakeFile.Visibility.OK)

  def test_is_accessible_none_filename(self):
    self.assertRaises(TypeError, stubs.FakeFile.is_file_accessible, None)

  def test_is_accessible_plist_on_mac(self):
    with mock.patch('sys.platform', 'darwin'):
      self.assertEqual(
          stubs.FakeFile.is_file_accessible('/Blah/Blah/Blah.plist'),
          stubs.FakeFile.Visibility.OK)


if __name__ == '__main__':
  unittest.main()
