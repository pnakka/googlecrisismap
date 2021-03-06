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

"""Data model and related access permissions."""

__author__ = 'lschumacher@google.com (Lee Schumacher)'

import datetime
import json

import cache
import domains
import logs
import perms
import users
import utils

from google.appengine.api import search
from google.appengine.ext import db
from google.appengine.ext import ndb

# A datetime value to represent null (the datastore cannot query on None).
NEVER = datetime.datetime.utcfromtimestamp(0)

# A GeoPt value to represent null (the datastore cannot query on None).
NOWHERE = ndb.GeoPt(90, 90)

# Individual CatalogEntries, keyed by domain name and label.  The 500-ms ULL
# is intended to beat the time it takes to manually navigate to a published
# map at its label after the label has been updated by clicking Publish.
CATALOG_ENTRY_CACHE = cache.Cache('model.catalog_entry', 300, 0.5)

# Lists of all CatalogEntries in a domain or across all domains, keyed by
# domain name or '*' for all domains.  The 100-ms ULL is intended to beat the
# time it takes to redirect back to /.maps after the user hits Publish.
CATALOG_CACHE = cache.Cache('model.catalog', 300, 0.1)

# Lists of the "listed" CatalogEntries in a domain or across all domains, keyed
# by domain name or '*' for all domains.  The 500-ms ULL is intended to beat
# the time it takes to manually navigate to any page with a map picker menu
# after editing which CatalogEntries are listed.
LISTED_CATALOG_CACHE = cache.Cache('model.listed_catalog', 300, 0.5)

# MapRoot data for published maps, keyed by [domain, label].  The 500-ms ULL
# is intended to beat the time it takes to manually navigate to a map after
# the user hits Publish to update the map.
PUBLISHED_MAP_ROOT_CACHE = cache.Cache('model.published_map_root', 300, 0.5)

# MapRoot data for maps, keyed by map ID.  The 500-ms ULL is intended to beat
# the time it takes to manually reload a map page after saving edits.
MAP_ROOT_CACHE = cache.Cache('model.map_root', 300, 0.5)

# Authorization entities are written offline, so users never expect to see
# immediate effects.  The 1000-ms ULL is intended to beat the time it takes for
# a developer to use an API key after editing an Authorization in the console.
AUTHORIZATION_CACHE = cache.Cache('model.authorization', 300, 1)


class MapVersionModel(db.Model):
  """A particular version of the JSON content of a Map.

  NOTE: This class is private to this module; outside code should use the Map
  class to create or access versions.

  If this entity is constructed properly, its parent entity will be a MapModel.
  """
  # The JSON string representing the map content, in MapRoot format.
  maproot_json = db.TextProperty()

  # Fields below are metadata for those with edit access, not for public
  # display.  No updated field is needed; these objects are immutable. Note
  # that it's possible that the creator_uid is historical - that is, it
  # represents a user whose account has been deleted - so any code that
  # tries to resolve it must be prepared for failure.
  created = db.DateTimeProperty()
  creator_uid = db.StringProperty()


class MapModel(db.Model):
  """A single map object and its associated metadata; parent of its versions.

  NOTE: This class is private to this module; outside code should use the Map
  class to create or access maps.

  The key_name is a unique ID.  The latest version is what's shown to viewers.
  """

  # Title for the current version.  Cached from the current version for display.
  # Plain text.
  title = db.StringProperty()

  # HTML description of the map.  Cached from current version for display.
  description = db.TextProperty()

  # Metadata for auditing and debugging purposes. Note that all uids could
  # be invalid; that happens when they represent a user whose account has been
  # deleted. Any code that tries to resolve them must be prepared for failure.
  created = db.DateTimeProperty()
  creator_uid = db.StringProperty()
  updated = db.DateTimeProperty()
  updater_uid = db.StringProperty()

  # To mark a map as deleted, set this to anything other than NEVER; the map
  # won't be returned by Map.Get* methods, though it remains in the datastore.
  deleted = db.DateTimeProperty(default=NEVER)
  deleter_uid = db.StringProperty()

  # To mark a map as blocked, set this to anything other than NEVER; then only
  # the first owner can view or edit the map, and the map cannot be published.
  blocked = db.DateTimeProperty(default=NEVER)
  blocker_uid = db.StringProperty()

  # User IDs of users who can set the flags and permission lists on this object.
  owners = db.StringListProperty()

  # User IDs of users who can edit this map.
  editors = db.StringListProperty()

  # User IDs of users who can review reports for this map.
  reviewers = db.StringListProperty()

  # User IDs of users who can view the current version of this map.
  # (Note that API keys can also be configured to grant access to view a map.)
  viewers = db.StringListProperty()

  # The domain that this map belongs to.  Required for all maps.
  domain = db.StringProperty(required=True)

  # Default role for users with e-mail domain equal to this map's domain.
  domain_role = db.StringProperty(choices=[perms.Role.NONE] + perms.MAP_ROLES)

  # World-readable maps can be viewed by anyone.
  world_readable = db.BooleanProperty(default=False)

  # Cache of the most recent MapVersion.
  current_version = db.ReferenceProperty(reference_class=MapVersionModel)


class CatalogEntryModel(db.Model):
  """A mapping from a (publisher domain, publication label) pair to a map.

  NOTE: This class is private to this module; outside code should use the
  CatalogEntry class to create or access catalog entries.

  The existence of a CatalogEntryModel with key_name "<domain>:<label>" causes
  the map to be available at the URL .../crisismap/a/<domain>/<label>.
  The catalog entry is like a snapshot; it points at a single MapVersionModel,
  so changes to the Map (i.e. new versions of the Map content) don't appear at
  .../crisismap/foo until the catalog entry is repointed at the new version.

  Each domain has a menu of maps (an instance of cm.MapPicker) that is shown
  on all the published map pages for that domain.  The menu shows a subset of
  the catalog entries in that domain, as selected by the is_listed flag.
  """

  # The domain and label (these are redundant with the key_name of the entity,
  # but broken out as separate properties so queries can filter on them).
  domain = db.StringProperty()
  label = db.StringProperty()

  # Metadata about the catalog entry itself.  Note that all uids could
  # be invalid; that happens when they represent a user whose account has been
  # deleted. Any code that tries to resolve them must be prepared for failure.
  created = db.DateTimeProperty()
  creator_uid = db.StringProperty()
  updated = db.DateTimeProperty()
  updater_uid = db.StringProperty()

  # The displayed title (in the crisis picker).  Set from the map_object.
  title = db.StringProperty()

  # The publisher name to display in the footer and below the map
  # title, in view-mode only.
  publisher_name = db.StringProperty()

  # The key_name of the map_version's parent MapModel (this is redundant with
  # map_version, but broken out as a property so queries can filter on it).
  map_id = db.StringProperty()

  # Reference to the map version published by this catalog entry.
  map_version = db.ReferenceProperty(MapVersionModel)

  # If true, this entry is shown in its domain's cm.MapPicker menu.
  is_listed = db.BooleanProperty(default=False)

  @staticmethod
  def Get(domain, label):
    return CatalogEntryModel.get_by_key_name(domain + ':' + label)

  @staticmethod
  def GetAll(domain=None):
    """Yields all CatalogEntryModels in reverse update order."""
    query = CatalogEntryModel.all().order('-updated')
    if domain:
      query = query.filter('domain =', domain)
    return query

  @staticmethod
  def GetListed(domain=None):
    """Yields all the listed CatalogEntryModels in reverse update order."""
    return CatalogEntryModel.GetAll(domain).filter('is_listed =', True)

  @staticmethod
  def Put(uid, domain, label, map_object, is_listed=False):
    """Stores a CatalogEntryModel pointing at the map's current version."""
    if ':' in domain:
      raise ValueError('Invalid domain %r' % domain)
    now = datetime.datetime.utcnow()
    entity = CatalogEntryModel.Get(domain, label)
    if not entity:
      entity = CatalogEntryModel(key_name=domain + ':' + label,
                                 domain=domain, label=label,
                                 created=now, creator_uid=uid)
    entity.updated = now
    entity.updater_uid = uid
    entity.title = map_object.title
    entity.map_id = map_object.id
    entity.map_version = map_object.GetCurrent().key
    entity.is_listed = is_listed
    entity.put()
    return entity


class CatalogEntry(object):
  """An access control wrapper around the CatalogEntryModel entity.

  All access from outside this module should go through CatalogEntry (never
  CatalogEntryModel).  Entries should always be created via CatalogEntry.Create.

  The MapRoot content of a CatalogEntry is always considered publicly readable,
  independent of the permission settings on the Map object.
  """

  def __init__(self, catalog_entry_model):
    """Constructor not to be called directly.  Use Create instead."""
    self.model = catalog_entry_model

  @staticmethod
  def Get(domain, label):
    """Returns the CatalogEntry for a domain and label if it exists, or None."""
    # We reserve the label 'empty' in all domains for a catalog entry pointing
    # at the empty map.  Handy for development.
    if label == 'empty':
      return EmptyCatalogEntry(domain)

    # No access control; all catalog entries are publicly visible.
    def GetFromDatastore():
      model = CatalogEntryModel.Get(domain, label)
      return model and CatalogEntry(model)

    return CATALOG_ENTRY_CACHE.Get([domain, label], GetFromDatastore)

  @staticmethod
  def GetAll(domain=None):
    """Gets all entries, possibly filtered by domain."""
    # No access control; all catalog entries are publicly visible.
    # We use '*' in the cache key for the list that includes all domains.
    return CATALOG_CACHE.Get(
        domain or '*',
        lambda: map(CatalogEntry, CatalogEntryModel.GetAll(domain)))

  @staticmethod
  def GetListed(domain=None):
    """Gets all entries marked listed, possibly filtered by domain."""
    # No access control; all catalog entries are publicly visible.
    # We use '*' in the cache key for the list that includes all domains.
    return LISTED_CATALOG_CACHE.Get(
        domain or '*',
        lambda: map(CatalogEntry, CatalogEntryModel.GetListed(domain)))

  @staticmethod
  def GetByMapId(map_id):
    """Returns all entries that point at a particular map."""
    return [CatalogEntry(model)
            for model in CatalogEntryModel.GetAll().filter('map_id =', map_id)]

  # TODO(kpy): First argument should be a user.
  @classmethod
  def Create(cls, domain_name, label, map_object, is_listed=False):
    """Stores a new CatalogEntry with version set to the map's current version.

    If a CatalogEntry already exists with the same label, and the user is
    allowed to overwrite it, it is overwritten.

    Args:
      domain_name: The domain in which to create the CatalogEntry.
      label: The publication label to use for this map.
      map_object: The Map object whose current version to use.
      is_listed: If True, show this entry in the map picker menu.
    Returns:
      The new CatalogEntry object.
    Raises:
      ValueError: If the domain string is invalid.
    """
    domain_name = str(domain_name)  # accommodate Unicode strings
    domain = domains.Domain.Get(domain_name)
    if not domain:
      raise ValueError('Unknown domain %r' % domain_name)
    perms.AssertAccess(perms.Role.CATALOG_EDITOR, domain_name)
    perms.AssertAccess(perms.Role.MAP_VIEWER, map_object)
    perms.AssertPublishable(map_object)
    # If catalog is sticky, only a creator or domain admin may update an entry.
    if (domain.has_sticky_catalog_entries and
        not perms.CheckAccess(perms.Role.DOMAIN_ADMIN, domain_name)):
      entry = CatalogEntryModel.Get(domain_name, label)
      if entry:
        perms.AssertCatalogEntryOwner(entry)
    entry = CatalogEntryModel.Put(
        users.GetCurrent().id, domain_name, label, map_object, is_listed)
    logs.RecordEvent(logs.Event.MAP_PUBLISHED, domain_name=domain_name,
                     map_id=map_object.id,
                     map_version_key=entry.map_version.key().name(),
                     catalog_entry_key=domain_name + ':' + label,
                     uid=users.GetCurrent().id)
    cls.FlushCaches(domain_name)
    CATALOG_ENTRY_CACHE.Delete([domain_name, label])
    return CatalogEntry(entry)

  @staticmethod
  def FlushCaches(domain_name):
    """Flushes the cached lists of catalog entries for a given domain."""
    CATALOG_CACHE.Delete(domain_name)
    LISTED_CATALOG_CACHE.Delete(domain_name)
    # We use '*' as the cache key for the list that includes all domains.
    CATALOG_CACHE.Delete('*')
    LISTED_CATALOG_CACHE.Delete('*')

  @classmethod
  def Delete(cls, domain_name, label, user=None):
    """Deletes an existing CatalogEntry.

    Args:
      domain_name: The domain to which the CatalogEntry belongs.
      label: The publication label.
      user: (optional) the user initiating the delete, or None for
        the current user.

    Raises:
      ValueError: if there's no CatalogEntry with the given domain and label.
    """
    if not user:
      user = users.GetCurrent()
    domain_name = str(domain_name)  # accommodate Unicode strings
    domain = domains.Domain.Get(domain_name)
    if not domain:
      raise ValueError('Unknown domain %r' % domain_name)
    entry = CatalogEntryModel.Get(domain_name, label)
    if not entry:
      raise ValueError('No CatalogEntry %r in domain %r' % (label, domain_name))
    perms.AssertAccess(perms.Role.CATALOG_EDITOR, domain_name)
    # If catalog is sticky, only a creator or domain admin may delete an entry.
    if (domain.has_sticky_catalog_entries and
        not perms.CheckAccess(perms.Role.DOMAIN_ADMIN, domain_name)):
      perms.AssertCatalogEntryOwner(entry)

    # Grab all the log information before we delete the entry
    map_id, version_key = entry.map_id, entry.map_version.key().name()
    entry_key = entry.key().name()
    entry.delete()
    logs.RecordEvent(logs.Event.MAP_UNPUBLISHED, domain_name=domain_name,
                     map_id=map_id, map_version_key=version_key,
                     catalog_entry_key=entry_key, uid=user.id)
    cls.FlushCaches(domain_name)
    CATALOG_ENTRY_CACHE.Delete([domain_name, label])

  # TODO(kpy): Make Delete and DeleteByMapId both take a user argument, and
  # reuse Delete here by calling it with an admin user.
  @classmethod
  def DeleteByMapId(cls, map_id):
    """NO ACCESS CHECK.  Deletes every CatalogEntry pointing at a given map."""
    for entry in CatalogEntry.GetByMapId(map_id):
      domain, label = str(entry.domain), entry.label
      entry = CatalogEntryModel.Get(domain, label)
      entry.delete()
      CATALOG_ENTRY_CACHE.Delete([domain, label])
      cls.FlushCaches(domain)

  is_listed = property(
      lambda self: self.model.is_listed,
      lambda self, value: setattr(self.model, 'is_listed', value))

  id = property(lambda self: self.model.key().name())

  # The datastore key of this catalog entry's MapVersionModel.
  def GetMapVersionKey(self):
    return CatalogEntryModel.map_version.get_value_for_datastore(self.model)
  map_version_key = property(GetMapVersionKey)

  # A string ID for the map version, in the form <map-id>@<version-id>.
  map_version_id = property(
      lambda self: '%s@%s' % tuple(self.map_version_key.to_path()[1::2]))

  # map_root gets the (possibly cached) MapRoot data for this entry.
  def GetMapRoot(self):
    return PUBLISHED_MAP_ROOT_CACHE.Get(
        [self.domain, self.label],
        lambda: json.loads(self.model.map_version.maproot_json))
  map_root = property(GetMapRoot)

  # Make the other properties of the CatalogEntryModel visible on CatalogEntry.
  for x in ['domain', 'label', 'map_id', 'title', 'publisher_name',
            'created', 'creator_uid', 'updated', 'updater_uid']:
    locals()[x] = property(lambda self, x=x: getattr(self.model, x))

  # Handy access to the user profiles associated with user IDs.
  creator = property(lambda self: users.Get(self.creator_uid))
  updater = property(lambda self: users.Get(self.updater_uid))

  def SetMapVersion(self, map_object):
    """Points this entry at the specified MapVersionModel."""
    self.model.map_id = map_object.id
    self.model.map_version = map_object.GetCurrent().key
    self.model.title = map_object.title

  def SetPublisherName(self, publisher_name):
    """Sets the publisher name to be displayed in the map viewer."""
    self.model.publisher_name = publisher_name

  def Put(self):
    """Saves any modifications to the datastore."""
    domain_name = str(self.domain)  # accommodate Unicode strings
    perms.AssertAccess(perms.Role.CATALOG_EDITOR, domain_name)
    # If catalog is sticky, only a creator or domain admin may update an entry.
    domain = domains.Domain.Get(domain_name)
    if not domain:
      raise ValueError('Unknown domain %r' % domain_name)
    # TODO(kpy): We could use a perms function for this catalog entry check.
    if (domain.has_sticky_catalog_entries and
        not perms.CheckAccess(perms.Role.DOMAIN_ADMIN, domain_name)):
      perms.AssertCatalogEntryOwner(self.model)

    self.model.updater_uid = users.GetCurrent().id
    self.model.updated = datetime.datetime.utcnow()
    self.model.put()
    logs.RecordEvent(logs.Event.MAP_PUBLISHED, domain_name=domain_name,
                     map_id=self.map_id,
                     map_version_key=self.GetMapVersionKey().name(),
                     catalog_entry_key=self.id,
                     uid=users.GetCurrent().id)
    self.FlushCaches(domain_name)
    PUBLISHED_MAP_ROOT_CACHE.Delete([domain_name, self.label])
    CATALOG_ENTRY_CACHE.Delete([domain_name, self.label])


class Map(object):
  """An access control wrapper around the MapModel entity.

  All access from outside this module should go through Map (never MapModel).
  Maps should always be created with Map.Create, which ensures that every map
  has at least one version.
  """

  # NOTE(kpy): Every public static method or public impure method should
  # call self.AssertAccess(...) first!

  NAMESPACE = 'Map'  # cache namespace

  def __init__(self, map_model):
    """Constructor not to be called directly."""
    self.model = map_model

  def __eq__(self, other):
    return isinstance(other, Map) and self.model.key() == other.model.key()

  def __hash__(self):
    return hash(self.model)

  # The datastore key for this map's MapModel entity.
  key = property(lambda self: self.model.key())

  # The datastore key for this map's latest MapVersionModel.
  current_version_key = property(
      lambda self: MapModel.current_version.get_value_for_datastore(self.model))

  # A string ID for the current map version, in the form <map-id>@<version-id>.
  current_version_id = property(
      lambda self: '%s@%s' % tuple(self.current_version_key.to_path()[1::2]))

  # Map IDs are in base64, so they are safely convertible from Unicode to ASCII.
  id = property(lambda self: str(self.model.key().name()))

  # Make the other properties of the underlying MapModel readable on the Map.
  for x in ['created', 'creator_uid', 'updated', 'updater_uid',
            'blocked', 'blocker_uid', 'deleted', 'deleter_uid',
            'title', 'description', 'current_version', 'world_readable',
            'owners', 'editors', 'reviewers', 'viewers',
            'domain', 'domain_role']:
    locals()[x] = property(lambda self, x=x: getattr(self.model, x))

  # Handy access to the user profiles associated with user IDs.
  creator = property(lambda self: users.Get(self.creator_uid))
  updater = property(lambda self: users.Get(self.updater_uid))
  blocker = property(lambda self: users.Get(self.blocker_uid))
  deleter = property(lambda self: users.Get(self.deleter_uid))

  # Handy Boolean access to the blocked or deleted status.
  is_blocked = property(lambda self: self.blocked != NEVER)
  is_deleted = property(lambda self: self.deleted != NEVER)

  @staticmethod
  def get(key):  # lowercase to match db.Model.get  # pylint: disable=g-bad-name
    return Map(MapModel.get(key))

  @staticmethod
  def _GetAll(domain=None):
    """NO ACCESS CHECK.  Yields all non-deleted maps; can filter by domain."""
    query = MapModel.all().order('-updated').filter('deleted =', NEVER)
    if domain:
      query = query.filter('domain =', domain)
    return (Map(model) for model in query)

  @staticmethod
  def GetAll(domain=None):
    """Yields all non-deleted maps, possibly filtered by domain."""
    perms.AssertAccess(perms.Role.ADMIN)
    return Map._GetAll(domain)

  @staticmethod
  def GetViewable(user, domain=None):
    """Yields all maps visible to the user, possibly filtered by domain."""
    # TODO(lschumacher): This probably won't scale to a large number of maps.
    # Also, we should only project the fields we want.
    # Share the AccessPolicy object to avoid fetching access lists repeatedly.
    policy = perms.AccessPolicy()
    for m in Map._GetAll(domain):
      if m.CheckAccess(perms.Role.MAP_VIEWER, user, policy=policy):
        yield m

  @staticmethod
  def Get(key_name, user=None):
    """Gets a Map by its map ID (key_name), or returns None if none exists.

    Args:
      key_name: A map ID.
      user: Optional.  If specified, access checks are done as this user.
    Returns:
      A Map object, or None.
    """
    # We reserve the special ID '0' for an empty map.  Handy for development.
    if key_name == '0':
      return EmptyMap()
    model = MapModel.get_by_key_name(key_name)
    if model and model.deleted == NEVER:
      map_object = Map(model)
      map_object.AssertAccess(perms.Role.MAP_VIEWER, user)
      return map_object

  @staticmethod
  def GetDeleted(key_name):
    """Gets a deleted Map by its ID.  Returns None if no map or not deleted."""
    perms.AssertAccess(perms.Role.ADMIN)
    model = MapModel.get_by_key_name(key_name)
    return model and model.deleted != NEVER and Map(model)

  @staticmethod
  def DeleteAllMapsWithNoOwner():
    """Deletes maps that have no owners. Returns a description of each map."""
    perms.AssertAccess(perms.Role.ADMIN)
    deleted_map_descs = []
    for m in Map.GetAll():
      if not m.owners:
        map_desc = 'Map "%s" (%s) created on %s by %s' % (
            m.title, m.description, m.created, m.creator_uid)
        deleted_map_descs.append(map_desc)
        m.Delete()
    return deleted_map_descs

  @staticmethod
  def RemoveUsers(users_to_remove):
    """Removes users from all permissions fields in maps.

    Args:
      users_to_remove: list of users to remove.
    Returns:
      A list of messages describing where users were removed from.
    """
    msg_list = []
    if not users_to_remove:
      return msg_list
    perms.AssertAccess(perms.Role.ADMIN)
    # TODO(andriy): change this to do transactional updates of MapModels, since
    # it's possible that while we have a map someone else can be modifying it,
    # leading to loss of data.  Determine what other methods need to become
    # transactional as a result (e.g. RevokePermission and similar methods).
    for m in Map.GetAll():
      map_users = {'Owners': m.owners, 'Editors': m.editors,
                   'Reviewers': m.reviewers, 'Viewers': m.viewers}
      for user in users_to_remove:
        for role in map_users:
          if user.id in map_users[role]:
            msg = 'Removed user [%s] from map [%s - %s] %s' % (user.email, m.id,
                                                               m.title, role)
            msg_list.append(msg)
            map_users[role].remove(user.id)
      m.model.put()
    return msg_list

  @staticmethod
  def Create(map_root, domain_name, owners=None, editors=None, reviewers=None,
             viewers=None, world_readable=False):
    """Stores a new map with the given properties and MapRoot content."""
    # map_root must be an object serializable as JSON, but otherwise we don't
    # check for MapRoot validity here.

    # TODO(rew): Change the domain argument to take a domains.Domain instead
    # of a string
    domain = domains.Domain.Get(domain_name)
    if not domain:
      raise ValueError('No such domain %r' % domain_name)
    perms.AssertAccess(perms.Role.MAP_CREATOR, domain.name)
    if owners is None:
      # TODO(kpy): Take user as an argument instead of calling GetCurrent.
      owners = [users.GetCurrent().id]
    if editors is None:
      editors = []
    if reviewers is None:
      reviewers = []
    if viewers is None:
      viewers = []
    if domain.initial_domain_role:
      domain_subjects = set(perms.GetSubjectsForTarget(domain.name).keys())
      if domain.initial_domain_role == perms.Role.MAP_OWNER:
        owners = list(set(owners) | domain_subjects)
      elif domain.initial_domain_role == perms.Role.MAP_EDITOR:
        editors = list(set(editors) | domain_subjects)
      elif domain.initial_domain_role == perms.Role.MAP_REVIEWER:
        reviewers = list(set(reviewers) | domain_subjects)
      elif domain.initial_domain_role == perms.Role.MAP_VIEWER:
        viewers = list(set(viewers) | domain_subjects)

    map_object = Map(MapModel(
        key_name=utils.MakeRandomId(),
        created=datetime.datetime.utcnow(), creator_uid=users.GetCurrent().id,
        owners=owners, editors=editors, reviewers=reviewers, viewers=viewers,
        domain=domain.name, domain_role=domain.initial_domain_role,
        world_readable=world_readable))
    map_object.PutNewVersion(map_root)  # also puts the MapModel
    return map_object

  @staticmethod
  def _GetVersionByKey(key):
    """NO ACCESS CHECK.  Returns a map version by its datastore entity key."""
    return utils.StructFromModel(MapVersionModel.get(key))

  def PutNewVersion(self, map_root):
    """Stores a new MapVersionModel object for this Map and returns its ID."""
    self.AssertAccess(perms.Role.MAP_EDITOR)
    map_root = dict(map_root, id=self.model.key().name())  # ensure correct ID
    now = datetime.datetime.utcnow()
    uid = users.GetCurrent().id
    new_version = MapVersionModel(
        parent=self.model, creator_uid=uid, created=now,
        maproot_json=json.dumps(map_root))

    # Update the MapModel from fields in the MapRoot.
    self.model.title = map_root.get('title', '')
    self.model.description = map_root.get('description', '')
    self.model.updated = now
    self.model.updater_uid = uid

    def PutModels():
      self.model.current_version = new_version.put()
      self.model.put()
    db.run_in_transaction(PutModels)
    MAP_ROOT_CACHE.Delete(self.id)
    return new_version.key().id()

  def GetCurrent(self):
    """Gets this map's latest version.

    Returns:
      A utils.Struct with the properties of this map's current version, along
      with a property 'id' containing the version's ID; or None if the current
      version has not been set.  (Version IDs are not necessarily in creation
      order, and are unique within a particular Map but not across all Maps.)
    """
    # A Map object can only be retrieved by a user who has MAP_VIEWER access
    # to it, so we don't need to check access again here.
    struct = utils.StructFromModel(self.current_version)
    # TODO(kpy): These __dict__ shenanigans can go away after we switch to ndb.
    struct.__dict__['map_root'] = json.loads(struct.maproot_json or '{}')
    del struct.__dict__['maproot_json']
    return struct

  def Delete(self):
    """Marks a map as deleted (so it won't be returned by Get or GetAll)."""
    self.AssertAccess(perms.Role.MAP_OWNER)
    self.model.deleted = datetime.datetime.utcnow()
    self.model.deleter_uid = users.GetCurrent().id
    CatalogEntry.DeleteByMapId(self.id)
    self.model.put()
    logs.RecordEvent(logs.Event.MAP_DELETED, map_id=self.id,
                     uid=self.model.deleter_uid)
    MAP_ROOT_CACHE.Delete(self.id)

  def Undelete(self):
    """Unmarks a map as deleted."""
    self.AssertAccess(perms.Role.ADMIN)
    self.model.deleted = NEVER
    self.model.deleter_uid = None
    self.model.put()
    logs.RecordEvent(logs.Event.MAP_UNDELETED, map_id=self.id,
                     uid=users.GetCurrent().id)
    MAP_ROOT_CACHE.Delete(self.id)

  def SetBlocked(self, block):
    """Sets whether a map is blocked (private to one user and unpublishable)."""
    perms.AssertAccess(perms.Role.ADMIN)
    if block:
      self.model.blocked = datetime.datetime.utcnow()
      self.model.blocker_uid = users.GetCurrent().id
      CatalogEntry.DeleteByMapId(self.id)
      logs.RecordEvent(logs.Event.MAP_BLOCKED, map_id=self.id,
                       uid=self.model.blocker_uid)
    else:
      self.model.blocked = NEVER
      self.model.blocker_uid = None
      logs.RecordEvent(logs.Event.MAP_UNBLOCKED, map_id=self.id,
                       uid=users.GetCurrent().id)
    self.model.put()
    MAP_ROOT_CACHE.Delete(self.id)

  def Wipe(self):
    """Permanently destroys a map."""
    self.AssertAccess(perms.Role.ADMIN)
    CatalogEntry.DeleteByMapId(self.id)
    map_id, domain_name = self.id, self.domain
    db.delete([self.model] + list(MapVersionModel.all().ancestor(self.model)))
    logs.RecordEvent(logs.Event.MAP_WIPED, domain_name=domain_name,
                     map_id=map_id, uid=users.GetCurrent().id)

  def GetMapRoot(self):
    """Gets the current version of the MapRoot definition of this map."""
    # A Map object can only be retrieved by a user who has MAP_VIEWER access
    # to it, so we don't need to check access again here.
    return MAP_ROOT_CACHE.Get(self.id, lambda: self.GetCurrent().map_root)

  map_root = property(GetMapRoot)

  def GetVersions(self):
    """Yields all versions of this map in order from newest to oldest."""
    self.AssertAccess(perms.Role.MAP_EDITOR)
    query = MapVersionModel.all().ancestor(self.model).order('-created')
    return utils.ResultIterator(query)

  def GetVersion(self, version_id):
    """Returns a specific version of this map."""
    self.AssertAccess(perms.Role.MAP_EDITOR)
    version = MapVersionModel.get_by_id(version_id, parent=self.model.key())
    return utils.StructFromModel(version)

  def SetWorldReadable(self, world_readable):
    """Sets whether the map is world-readable."""
    self.AssertAccess(perms.Role.MAP_OWNER)
    self.model.world_readable = world_readable
    self.model.put()

  def RevokePermission(self, role, uid):
    """Revokes user permissions for the map."""
    self.AssertAccess(perms.Role.MAP_OWNER)
    # Does nothing if the user does not have the role to begin with or if
    # the role is not editor, viewer, or owner.
    if role == perms.Role.MAP_VIEWER and uid in self.model.viewers:
      self.model.viewers.remove(uid)
    if role == perms.Role.MAP_REVIEWER and uid in self.model.reviewers:
      self.model.reviewers.remove(uid)
    elif role == perms.Role.MAP_EDITOR and uid in self.model.editors:
      self.model.editors.remove(uid)
    elif role == perms.Role.MAP_OWNER and uid in self.model.owners:
      self.model.owners.remove(uid)
    self.model.put()

  def ChangePermissionLevel(self, role, uid):
    """Changes the user's level of permission."""
    # When a user's permission is changed to viewer, editor, or owner,
    # their former permission level is revoked.
    # Does nothing if role is not in permissions.
    self.AssertAccess(perms.Role.MAP_OWNER)
    permissions = [perms.Role.MAP_VIEWER, perms.Role.MAP_REVIEWER,
                   perms.Role.MAP_EDITOR, perms.Role.MAP_OWNER]
    if role not in permissions:
      return
    elif role == perms.Role.MAP_VIEWER and uid not in self.model.viewers:
      self.model.viewers.append(uid)
    elif role == perms.Role.MAP_REVIEWER and uid not in self.model.reviewers:
      self.model.reviewers.append(uid)
    elif role == perms.Role.MAP_EDITOR and uid not in self.model.editors:
      self.model.editors.append(uid)
    elif role == perms.Role.MAP_OWNER and uid not in self.model.owners:
      self.model.owners.append(uid)

    # Take away the other permissions
    for permission in permissions:
      if permission != role:
        self.RevokePermission(permission, uid)
    self.model.put()

  def CheckAccess(self, role, user=None, policy=None):
    """Checks whether a user has the specified access role for this map."""
    return perms.CheckAccess(role, self, user, policy=policy)

  def AssertAccess(self, role, user=None, policy=None):
    """Requires a user to have the specified access role for this map."""
    perms.AssertAccess(role, self, user, policy=policy)


class EmptyMap(Map):
  """An empty stand-in for a Map object (handy for development)."""

  # To ensure that the app has something to display, we return this special
  # empty map object as the map with ID '0'.
  TITLE = 'Empty map'
  DESCRIPTION = 'This is an empty map for testing.'
  MAP_ROOT = {'title': TITLE, 'description': DESCRIPTION}

  def __init__(self):
    Map.__init__(self, MapModel(
        key_name='0', owners=[], editors=[], reviewers=[], viewers=[],
        domain='gmail.com', world_readable=True,
        title=self.TITLE, description=self.DESCRIPTION))

  def GetCurrent(self):
    key = db.Key.from_path('MapModel', '0', 'MapVersionModel', 1)
    return utils.Struct(id=1, key=key, map_root=self.MAP_ROOT)

  def GetVersions(self):
    return [self.GetCurrent()]

  def GetVersion(self, version_id):
    if version_id == 1:
      return self.GetCurrent()

  def ReadOnlyError(self, *unused_args, **unused_kwargs):
    raise TypeError('EmptyMap is read-only')

  SetWorldReadable = ReadOnlyError
  PutNewVersion = ReadOnlyError
  Delete = ReadOnlyError
  RevokePermission = ReadOnlyError
  ChangePermissionLevel = ReadOnlyError


class EmptyCatalogEntry(CatalogEntry):
  """An empty stand-in for a CatalogEntry object (handy for development)."""

  # To ensure that the app has something to display, we return this special
  # catalog entry as the entry with label 'empty' in all domains.
  def __init__(self, domain):
    CatalogEntry.__init__(self, CatalogEntryModel(
        domain=domain, label='empty', title=EmptyMap.TITLE, map_id='0'))

  map_root = property(lambda self: EmptyMap.MAP_ROOT)

  def ReadOnlyError(self, *unused_args, **unused_kwargs):
    raise TypeError('EmptyCatalogEntry is read-only')

  SetMapVersion = ReadOnlyError
  Put = ReadOnlyError


class _CrowdReportModel(ndb.Model):
  """A crowd report.  Entity id: a unique URL with source as a prefix."""

  # A URL identifying the original repository in which the report was created.
  source = ndb.StringProperty()

  # A unique URL identifying the author.
  author = ndb.StringProperty()

  # The time of the observation or prediction that this report is about.
  effective = ndb.DateTimeProperty()

  # The time that this report or its latest edit was submitted into its
  # original repository by the author.
  submitted = ndb.DateTimeProperty()

  # The time of the last write to any field owned by this datastore entity.
  # This includes, for example: report created in this repository; report
  # edited in this repository; report copied into this repository via an API
  # or import from another repository.  It does not include writes to fields
  # computed from other entities (upvote_count, downvote_count, score, hidden).
  updated = ndb.DateTimeProperty()

  # Text of the user's comment.
  text = ndb.TextProperty()

  # Optional map to which this report belongs.  If map_id is empty, this report
  # is publicly accessible.  If map_id is specified, this report is accessible
  # only to signed-in users who have MAP_VIEWER access to the specified map.
  # (There's no requirement for this to match any element of topic_ids.)
  map_id = ndb.StringProperty()

  # Topics (within maps) to which this report belongs.  Topic IDs should be
  # globally unique across all topics in all maps.  (As currently implemented,
  # this field begins with map_id + '.' to ensure said uniqueness.)
  topic_ids = ndb.StringProperty(repeated=True)

  # Survey answers in this report, as a JSON dictionary.  The keys are in the
  # form topic_id + '.' + question_id, and the values are answers (strings
  # for TEXT questions, numbers for NUMBER questions, or choice IDs for CHOICE
  # questions).  Note that the definitions of questions and choices can be
  # edited, and we do not record the version of the question and choice that
  # was current at the time that the answer was submitted.
  answers_json = ndb.TextProperty()

  # The report's geolocation coordinates.
  location = ndb.GeoPtProperty()

  # An identifier for the place where the report is located.  We don't enforce
  # any format or semantics for the identifier; it just needs to be unique.
  place_id = ndb.StringProperty()

  # Number of positive and negative votes for this report, respectively.
  upvote_count = ndb.IntegerProperty(default=0)
  downvote_count = ndb.IntegerProperty(default=0)

  # Aggregate score for this report.
  score = ndb.FloatProperty(default=0)

  # True if the report should be hidden because its score is too low.
  hidden = ndb.BooleanProperty(default=False)

  # True if the report has been reviewed for spam content.
  reviewed = ndb.BooleanProperty(default=False)

  @classmethod
  def _get_kind(cls):  # pylint: disable=g-bad-name
    return 'CrowdReportModel'  # so we can name the Python class with a _


class CrowdReport(utils.Struct):
  """Application-level object representing a crowd report."""
  index = search.Index('CrowdReport')

  answers = property(lambda self: json.loads(self.answers_json or '{}'))

  @staticmethod
  def GenerateId(source):
    """Generates a new, unique report ID (a URL under the given source URL)."""
    unique_int_id, _ = _CrowdReportModel.allocate_ids(1)
    return source.rstrip('/') + '/.reports/' + str(unique_int_id)

  @classmethod
  def Get(cls, report_id):
    """Gets the report with the given report_id.

    Args:
      report_id: The key.string_id() of the _CrowdReportModel to retrieve

    Returns:
      A struct representing the CrowdReport, or None if no such report exists.
    """
    report = _CrowdReportModel.get_by_id(report_id)
    if report and report.map_id:
      report = Map.Get(report.map_id) and report  # ensures MAP_VIEWER access
    return cls.FromModel(report)

  @classmethod
  def _FilterReports(cls, entities):
    """Filters out inaccessible reports and yields CrowdReport objects."""

    class MapViewableCache(dict):
      """Checks and caches whether maps are viewable by the current user."""

      def __missing__(self, map_id):
        try:
          self[map_id] = bool(Map.Get(map_id))
        except perms.AuthorizationError:
          self[map_id] = False
        return self[map_id]  # True if map exists and is viewable by user

    is_map_viewable = MapViewableCache()
    for entity in entities:
      if entity and (not entity.map_id or is_map_viewable[entity.map_id]):
        yield cls.FromModel(entity)

  @classmethod
  def GetForAuthor(cls, author, count, offset=0, hidden=None, reviewed=None):
    """Gets reports by the given author, across maps and topics.

    Args:
      author: A string matching _CrowdReportModel.author
      count: The maximum number of reports to retrieve.
      offset: The number of reports to skip, for paging cases.
      hidden: A boolean; if specified, only get reports whose hidden flag
          matches this value.  (Otherwise, include both hidden and unhidden.)
      reviewed: A boolean; if specified, only get reports whose reviewed flag
          matches this value.  (Otherwise, include reviewed and unreviewed.)

    Returns:
      An iterator giving the 'count' most recently updated CrowdReport objects,
      in order by decreasing update time, that have the given author.  (Note
      that fewer than 'count' objects may be returned if some are restricted
      such that the current user cannot see them.)
    """
    if not author:
      return []
    query = _CrowdReportModel.query().order(-_CrowdReportModel.updated)
    query = query.filter(_CrowdReportModel.author == author)
    if hidden is not None:
      query = query.filter(_CrowdReportModel.hidden == hidden)
    if reviewed is not None:
      query = query.filter(_CrowdReportModel.reviewed == reviewed)
    return cls._FilterReports(query.fetch(count, offset=offset))

  @classmethod
  def GetForTopics(cls, topic_ids, count, offset=0,
                   author=None, hidden=None, reviewed=None):
    """Gets reports with any of the given topic_ids.

    Args:
      topic_ids: A list of strings in the form map_id + '.' + topic_id.
      count: The maximum number of reports to retrieve.
      offset: The number of reports to skip, for paging cases.
      author: A string matching _CrowdReportModel.author; if specified, restrict
              to reports from this author.
      hidden: A boolean; if specified, only get reports whose hidden flag
          matches this value.  (Otherwise, include both hidden and unhidden.)
      reviewed: A boolean; if specified, only get reports whose reviewed flag
          matches this value.  (Otherwise, include reviewed and unreviewed.)

    Returns:
      An iterator giving the 'count' most recently updated CrowdReport objects,
      in order by decreasing update time, that have any of the given topic_ids.
      (Note that fewer than 'count' objects may be returned if some are
      restricted such that the current user cannot see them.)
    """
    if not topic_ids:
      return []
    query = _CrowdReportModel.query().order(-_CrowdReportModel.updated)
    query = query.filter(_CrowdReportModel.topic_ids.IN(topic_ids))
    if author is not None:
      query = query.filter(_CrowdReportModel.author == author)
    if hidden is not None:
      query = query.filter(_CrowdReportModel.hidden == hidden)
    if reviewed is not None:
      query = query.filter(_CrowdReportModel.reviewed == reviewed)
    return cls._FilterReports(query.fetch(count, offset=offset))

  @classmethod
  def GetWithoutLocation(cls, topic_ids, count, max_updated=None, hidden=None):
    """Gets reports with the given topic IDs that don't have locations.

    Args:
      topic_ids: A list of strings in the form map_id + '.' + topic_id.
      count: The maximum number of reports to retrieve.
      max_updated: A datetime; if specified, only get reports that were updated
          at or before this time.
      hidden: A boolean; if specified, only get reports whose hidden flag
          matches this value.  (Otherwise, include both hidden and unhidden.)

    Returns:
      An iterator giving the 'count' most recently updated Report objects, in
      order by decreasing update time, that meet the criteria:
        - Has at least one of the specified topic IDs
        - Has no location
        - Has an update time equal to or before 'max_updated'
      (Note that fewer than 'count' objects may be returned if some are
      restricted such that the current user cannot see them.)
    """
    query = _CrowdReportModel.query().order(-_CrowdReportModel.updated)
    query = query.filter(_CrowdReportModel.location == NOWHERE)
    if topic_ids:
      query = query.filter(_CrowdReportModel.topic_ids.IN(topic_ids))
    if max_updated:
      query = query.filter(_CrowdReportModel.updated <= max_updated)
    if hidden is not None:
      query = query.filter(_CrowdReportModel.hidden == hidden)
    return cls._FilterReports(query.fetch(count))

  @classmethod
  def GetByLocation(cls, center, topic_radii, count=1000, max_updated=None,
                    hidden=None):
    """Gets reports with the given topic IDs that are near a given location.

    Args:
      center: A ndb.GeoPt object.
      topic_radii: A dictionary of {topic_id: radius} items where topic_id has
          the form map_id + '.' + topic_id and radius is a distance in metres.
      count: The maximum number of reports to retrieve.
      max_updated: A datetime; if specified, only get reports that were updated
          at or before this time.
      hidden: A boolean; if specified, only get reports whose hidden flag
          matches this value.  (Otherwise, include both hidden and unhidden.)

    Returns:
      An iterator giving the 'count' most recently updated Report objects, in
      order by decreasing update time, that meet the criteria:
        - Has at least one of the specified topic IDs
        - Distance from report location to 'center' is less than the radius
          specified for at least one of its matching topic IDs
        - Has an update time equal to or before 'max_updated'
      (Note that fewer than 'count' objects may be returned if some are
      restricted such that the current user cannot see them.)
    """
    query = []
    for topic_id, radius in topic_radii.items():
      subquery = ['%s = "%s"' % ('topic_id', topic_id)]
      subquery.append('distance(location, geopoint(%f, %f)) < %f' %
                      (center.lat, center.lon, radius))
      if max_updated:
        subquery.append('%s <= %s' % ('updated',
                                      utils.UtcToTimestamp(max_updated)))
      if hidden is not None:
        subquery.append('hidden = %s' % bool(hidden))
      query.append('(' + ' '.join(subquery) + ')')

    options = search.QueryOptions(limit=count, ids_only=True)
    results = cls.index.search(search.Query(' OR '.join(query), options))
    ids = [ndb.Key(_CrowdReportModel, result.doc_id) for result in results]
    return cls._FilterReports(ndb.get_multi(ids))

  @classmethod
  def Search(cls, query, count=1000, max_updated=None):
    """Full-text structured search over reports.

    Args:
      query: A string; a query expression with the full range of syntax
          described at
          developers.google.com/appengine/docs/python/search/query_strings
          To search over a single field, append a GMail-style search
          operator matching one of the indexed fields:
          text, author, updated, topic_id.
          Examples:
              [text:"foo OR bar"] returns reports with foo or bar in the text
              [text:"bar" author:"http://foo.com/123"] returns reports from
                                                       http://foo.com/123 that
                                                       mention bar
      count: The maximum number of reports to retrieve.
      max_updated: A datetime; if specified, only get reports that were updated
          at or before this time.

    Returns:
      An iterator giving the 'count' most recently updated Report objects, in
      order by decreasing update time, that meet the criteria:
        - Matches the given query
        - Has an update time equal to or before 'max_updated'
      (Note that fewer than 'count' objects may be returned if some are
      restricted such that the current user cannot see them.)
    """
    if max_updated:
      query += ' (%s <= %s)' % ('updated', utils.UtcToTimestamp(max_updated))
    options = search.QueryOptions(limit=count, ids_only=True)
    results = cls.index.search(search.Query(query, options))
    ids = [ndb.Key(_CrowdReportModel, result.doc_id) for result in results]
    return cls._FilterReports(ndb.get_multi(ids))

  @classmethod
  def Create(cls, source, author, effective, text, topic_ids, answers,
             location, submitted=None, map_id=None, place_id=None,
             id=None):  # pylint: disable=redefined-builtin
    """Stores one new crowd report and returns it."""
    # TODO(kpy): We don't currently validate that 'answers' is a dictionary
    # with keys that are all valid question IDs, or that its values have the
    # appropriate types for those questions, or that the values are valid
    # choice IDs for CHOICE questions.  I'm doubtful that we should do this
    # until we have a clear plan for how these invariants would be enforced
    # (e.g. what should happen when a topic is edited -- scan all reports?).
    now = datetime.datetime.utcnow()
    report_id = id or cls.GenerateId(source)
    if not report_id.startswith(source):
      raise ValueError('ID %r not valid for source %s' % (report_id, source))
    model = _CrowdReportModel(
        id=report_id, source=source, author=author, effective=effective,
        submitted=submitted or now, updated=now, text=text,
        topic_ids=topic_ids or [], answers_json=json.dumps(answers or {}),
        location=location or NOWHERE, map_id=map_id, place_id=place_id)
    report = cls.FromModel(model)
    document = cls._CreateSearchDocument(model)

    # Prepare all the arguments for both put() calls before this point, to
    # minimize the possibility that one put() succeeds and the other fails.
    model.put()
    cls.index.put(document)
    return report

  @classmethod
  def _CreateSearchDocument(cls, model):
    # We index updated as a number because DateField has only date precision;
    # see http://developers.google.com/appengine/docs/python/search/
    fields = [
        search.NumberField('updated', utils.UtcToTimestamp(model.updated)),
        search.NumberField('score', model.score),
        search.TextField('text', model.text),
        search.TextField('author', model.author),
        # A 'True'/'False' AtomField is more efficient than a 0/1 NumberField.
        search.AtomField('hidden', str(bool(model.hidden))),
        search.AtomField('reviewed', str(bool(model.reviewed))),
    ] + [search.AtomField('topic_id', tid) for tid in model.topic_ids]
    if model.location:
      fields.append(search.GeoField(
          'location', search.GeoPoint(model.location.lat, model.location.lon)))
    return search.Document(doc_id=model.key.id(), fields=fields)

  @classmethod
  def MarkAsReviewed(cls, report_ids, reviewed=True):
    """Mark a report as reviewed for spam.

    Args:
      report_ids: A single report ID or iterable collection of report IDs.
      reviewed: True to mark the reports reviewed, false to mark unreviewed.
    """
    if isinstance(report_ids, basestring):
      report_ids = [report_ids]
    models = ndb.get_multi([ndb.Key(_CrowdReportModel, i) for i in report_ids])
    documents = []
    for model in models:
      model.reviewed = reviewed
      documents.append(cls._CreateSearchDocument(model))
    ndb.put_multi(models)
    cls.index.put(documents)

  @classmethod
  def UpdateScore(cls, report_id, old_vote=None, new_vote_type=None):
    """Updates the voting stats on the affected report.

    This method prospectively calculates the new voting stats on the report,
    factoring in an update to a single vote that hasn't been written yet.
    Call this just before storing or updating a vote in the datastore, and
    pass in old_vote and new_vote_type to describe what's about to change.

    Args:
      report_id: The ID of the report.
      old_vote: A CrowdVote or None, the vote that's about to be replaced.
      new_vote_type: A member of VOTE_TYPES or None, the vote about to be added.
    """
    # This method is designed this way because scanning the indexes immediately
    # after writing a vote is likely to produce incomplete counts; there's some
    # delay between when a vote is written and when the indexes are updated.
    # Also, we can't do the counting in a transaction, as non-ancestor queries
    # are not allowed.  So we count first and then adjust by one vote; this
    # still relies on indexes being up to date just before a vote is cast, but
    # that's more likely than being up to date just after a vote is cast.  So,
    # the situation in which a report ends up with the wrong score is when
    # (a) multiple people try to vote on the same report at the same time and
    # (b) no one votes on that report for a while afterward.  If a report is so
    # controversial that lots of conflicting votes come in quickly, being off
    # by a few votes is unlikely to sway the final hidden/unhidden outcome.
    def CountVotes(vote_type):
      return _CrowdVoteModel.query(
          _CrowdVoteModel.report_id == report_id,
          _CrowdVoteModel.vote_type == vote_type
      ).count() + (bool(new_vote_type == vote_type) -
                   bool(old_vote and old_vote.vote_type == vote_type))
    upvote_count = CountVotes('ANONYMOUS_UP')
    downvote_count = CountVotes('ANONYMOUS_DOWN')
    reviewer_upvote_count = CountVotes('REVIEWER_UP')
    reviewer_downvote_count = CountVotes('REVIEWER_DOWN')

    score = (upvote_count - downvote_count +
             # Reviewer votes count 1000x user votes
             1000 * (reviewer_upvote_count - reviewer_downvote_count))
    hidden = score <= -2  # for now, two downvotes hide a report
    cls.PutScoreForReport(
        report_id, upvote_count + reviewer_upvote_count,
        downvote_count + reviewer_downvote_count, score, hidden)

  @classmethod
  @ndb.transactional
  def PutScoreForReport(
      cls, report_id, upvote_count, downvote_count, score, hidden):
    """Atomically writes the voting stats on a report."""
    model = _CrowdReportModel.get_by_id(report_id)
    if model:
      model.upvote_count = upvote_count
      model.downvote_count = downvote_count
      model.score = score
      model.hidden = hidden
      document = cls._CreateSearchDocument(model)
      model.put()
      cls.index.put(document)

# Possible types of votes.  Each vote type is associated with a particular
# weight, and some vote types are only available to privileged users.
VOTE_TYPES = ['ANONYMOUS_UP', 'ANONYMOUS_DOWN', 'REVIEWER_UP', 'REVIEWER_DOWN']


class _CrowdVoteModel(ndb.Model):
  """A vote on a crowd report.  Entity id: report_id + '\x00' + voter."""

  # The entity ID of the report.
  report_id = ndb.StringProperty()

  # A unique URL identifying the voter.
  voter = ndb.StringProperty()

  # The type of vote, which determines its weight.  None is allowed, and
  # means that the vote has no weight (the user voted and then unvoted).
  vote_type = ndb.StringProperty(choices=VOTE_TYPES)

  @classmethod
  def _get_kind(cls):  # pylint: disable=g-bad-name
    return 'CrowdVoteModel'  # so the Python class can start with an underscore


class CrowdVote(utils.Struct):
  """Application-level object representing a crowd vote."""

  @classmethod
  def Get(cls, report_id, voter):
    """Gets the vote for a specified report and voter.

    Args:
      report_id: The ID of the report.
      voter: A unique URL identifying the voter.
    Returns:
      The CrowdVote object, or None if this voter has not voted on this report.
    """
    return cls.FromModel(_CrowdVoteModel.get_by_id(report_id + '\x00' + voter))

  @classmethod
  def GetMulti(cls, report_ids, voter):
    """Gets the votes by a given voter on multiple reports.

    Args:
      report_ids: A list of report IDs.
      voter: A unique URL identifying the voter.
    Returns:
      A dictionary mapping a subset of the report IDs to CrowdVote objects.
    """
    ids = [report_id + '\x00' + voter for report_id in report_ids]
    votes = ndb.get_multi([ndb.Key(_CrowdVoteModel, i) for i in ids])
    return {vote.report_id: cls.FromModel(vote) for vote in votes if vote}

  @classmethod
  def Put(cls, report_id, voter, vote_type):
    """Stores or replaces the vote for a specified report and voter.

    Args:
      report_id: The ID of the report.
      voter: A unique URL identifying the voter.
      vote_type: A member of VOTE_TYPES.
    """
    old_vote = CrowdVote.Get(report_id, voter)
    CrowdReport.UpdateScore(report_id, old_vote, vote_type)
    _CrowdVoteModel(id=report_id + '\x00' + voter, report_id=report_id,
                    voter=voter, vote_type=vote_type).put()


class _AuthorizationModel(ndb.Model):
  """API keys and their authorized actions.  key.id() is the API key."""

  # If this flag is False, this API key will be ignored.  Use this to disable
  # a key without deleting it.
  is_enabled = ndb.BooleanProperty()

  # Bookkeeping information for humans, not used programmatically.
  contact_name = ndb.StringProperty()
  contact_email = ndb.StringProperty()
  organization_name = ndb.StringProperty()

  # If this flag is True, then 'source' and 'map_ids' are required, and this
  # API key allows a client to post crowd reports with the specified source URL
  # and one of the allowed map IDs.
  crowd_report_write_permission = ndb.BooleanProperty()

  # If this flag is True, then incoming crowd reports are checked for spam.
  crowd_report_spam_check = ndb.BooleanProperty()

  # If this flag is True, then 'map_ids' is required, and this API key allows
  # a client to read the Map objects with the allowed map IDs.
  map_read_permission = ndb.BooleanProperty()

  # For crowd_report_write_permission, this specifies the source URL that
  # posted crowd reports are required to have.  Reports that have non-matching
  # source URLs are rejected.
  source = ndb.StringProperty()

  # For crowd_report_write_permission, this specifies the set of map IDs that
  # are allowed in posted crowd reports.  For map_read_permission, these are
  # the map IDs of the maps that are allowed to be read.
  map_ids = ndb.StringProperty(repeated=True)

  # For crowd_report_write_permission, if this field is non-empty, the posted
  # crowd reports are required to have author URLs beginning with this prefix.
  # Otherwise, any author URL is accepted.
  author_prefix = ndb.StringProperty(default='')

  @classmethod
  def _get_kind(cls):  # pylint: disable=g-bad-name
    return 'AuthorizationModel'  # so we can name the Python class with a _


class Authorization(utils.Struct):
  """Application-level object representing an API authorization record."""

  @classmethod
  def Get(cls, key):
    """Gets the authorization record for a given API key."""
    return AUTHORIZATION_CACHE.Get(
        key, lambda: cls.FromModel(_AuthorizationModel.get_by_id(key)))

  @classmethod
  def Create(cls, contact_name='', contact_email='', organization_name='',
             crowd_report_write_permission=False, crowd_report_spam_check=True,
             map_read_permission=False, source='', map_ids=None,
             author_prefix=''):
    key = utils.MakeRandomId()
    model = _AuthorizationModel(
        id=key, is_enabled=True, contact_name=contact_name,
        contact_email=contact_email, organization_name=organization_name,
        crowd_report_write_permission=crowd_report_write_permission,
        crowd_report_spam_check=crowd_report_spam_check,
        map_read_permission=map_read_permission, source=source,
        map_ids=map_ids or [], author_prefix=author_prefix)
    model.put()
    return cls.FromModel(model)

  @classmethod
  def SetEnabled(cls, key, enabled):
    entity = _AuthorizationModel.get_by_id(key)
    if not entity:
      raise ValueError('No such Authorization.')
    entity.is_enabled = enabled
    entity.put()
    AUTHORIZATION_CACHE.Delete(key)
