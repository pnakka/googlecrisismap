#!/usr/bin/python
# Copyright 2012 Google Inc.  All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License.  You may obtain a copy
# of the License at: http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distrib-
# uted under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, either express or implied.  See the License for
# specific language governing permissions and limitations under the License.

"""Configurable redirection service."""

__author__ = 'kpy@google.com (Ka-Ping Yee)'

import webapp2
from google.appengine.ext import db


class Redirection(db.Model):
  url = db.StringProperty()


class Redirect(webapp2.RequestHandler):
  """Configurable redirection service."""

  # "get" is part of the RequestHandler interface.  # pylint: disable-msg=C6409
  def get(self, key_name):
    redirection = Redirection.get_by_key_name(key_name)
    self.redirect(redirection and redirection.url or '/')


app = webapp2.WSGIApplication([
    (r'/crisismap/redirect/([\w.-]+)', Redirect)
    ])
