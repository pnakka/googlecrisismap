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

"""Handler for the list of published maps for a given domain."""

__author__ = 'lschumacher@google.com (Lee Schumacher)'

# base_handler must come first. pylint:disable=g-bad-import-order
from base_handler import BaseHandler
import webapp2
import model
from google.appengine.api import users


class Catalog(BaseHandler):
  """Handler for the list of published maps for a given domain."""

  # "get" is part of the RequestHandler interface.  # pylint: disable-msg=C6409
  def get(self, domain):
    """Displays the list of catalog entries."""
    entries = model.CatalogEntry.GetAllInDomain(domain)
    self.response.out.write(self.RenderTemplate('catalog.html', {
        'domain': domain,
        'entries': list(entries),
        'user_domain': model.GetUserDomain(users.get_current_user())
    }))

  def post(self, domain):
    """Changes the visibility of catalog entries in Map Picker."""
    entries = model.CatalogEntry.GetAllInDomain(domain)
    for entry in entries:
      # Only checked checkboxes' values are sent from the client.
      value = bool(self.request.get(entry.label))
      if bool(entry.is_listed) != value:
        entry.is_listed = value
        entry.Put()
    self.redirect('/crisismap/a/' + domain)


app = webapp2.WSGIApplication([(r'.*/([\w.-]+)', Catalog)])
