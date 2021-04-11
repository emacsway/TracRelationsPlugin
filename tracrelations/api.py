# -*- coding: utf-8 -*-
#
# Copyright (C) 2021 Cinc
#
# License: 3-clause BSD
#
from trac.core import Component, implements, TracError
from trac.db.api import DatabaseManager
from trac.db.schema import Column, Table
from trac.env import IEnvironmentSetupParticipant
from trac.ticket.admin import AbstractEnumAdminPanel
from trac.ticket.model import AbstractEnum, simplify_whitespace
from trac.util.text import to_unicode
from trac.util.translation import N_

from tracrelations.model import Relation


db_version_key = 'relation_version'
db_version = 1


tables_v1 = [
    Table('relation', key='id')[
        Column('id', auto_increment=True),
        Column('realm', type='text'),
        Column('source', type='text'),
        Column('dest', type='text'),
        Column('type', type='text')
        ],
    ]

table = """CREATE TABLE relation (
    id              integer PRIMARY KEY,
    realm           text,
    source          text,
    dest            text,
    type            text,
    UNIQUE(realm, source, dest, type)
);"""


class ValidationError(TracError):
    """Raised when validation of a relation fails."""


class RelationEnum(AbstractEnum):
    type = 'relation'

    def delete(self):
        """Delete the enum value.
        """
        assert self.exists, "Cannot delete non-existent %s" % self.type

        with self.env.db_transaction as db:
            self.env.log.info("Deleting %s %s", self.type, self.name)
            db("DELETE FROM enum WHERE type=%s AND value=%s",
               (self.type, self._old_value))
            # Re-order any enums that have higher value than deleted
            # (close gap)
            for enum in self.select(self.env):
                try:
                    if int(enum.value) > int(self._old_value):
                        enum.value = to_unicode(int(enum.value) - 1)
                        enum.update()
                except ValueError:
                    pass  # Ignore cast error for this non-essential operation

            # TODO: Remove from relations table
            #TicketSystem(self.env).reset_ticket_fields()

        self.value = self._old_value = None
        self.name = self._old_name = None

    def update(self):
        """Update the enum value.
        """
        assert self.exists, "Cannot update non-existent %s" % self.type
        self.name = simplify_whitespace(self.name)
        if not self.name:
            raise TracError(_("Invalid %(type)s name.", type=self.type))

        with self.env.db_transaction as db:
            self.env.log.info("Updating %s '%s'", self.type, self.name)
            db("UPDATE enum SET name=%s,value=%s WHERE type=%s AND name=%s",
               (self.name, self.value, self.type, self._old_name))
            # For Tracs enums we update the tickets here
            # ...

        self._old_name = self.name
        self._old_value = self.value


class RelationAdminPanel(AbstractEnumAdminPanel):
    _type = 'relation'
    _enum_cls = RelationEnum
    _label = N_("Relation"), N_("Relation")


def delete_relations_table(env):
    dbm = DatabaseManager(env)
    dbm.drop_tables(('relation',))

    with env.db_transaction as db:
        db("DELETE FROM system WHERE name='tracrelations_version'")
        db("DELETE FROM system WHERE name='tracrelation_version'")
        db("DELETE FROM system WHERE name='relation_version'")


def check_cycle(env, relation):
    """Check if the given relation causes a cycle.

    :param env: Trac Environment
    :param relation: a Relation with all necessary data

    Note that this function checks for relations of the same type and the same realm.
    """
    id_list = [relation['source'], relation['dest']]

    def find_cycle(relation, id_list):
        # Note that we add '->' and
        for rel in Relation.select(env, relation['realm'], src=relation['dest'], reltype=relation['type']):
            if rel['dest'] in id_list:
                # Make pretty error message here
                msg = ' -> '.join(id_list)
                raise ValidationError("Validation failed. Cycle detected %s -> %s" %
                                      (msg, rel['dest']))
            id_list.append(rel['dest'])
            find_cycle(rel, id_list)

    find_cycle(relation, id_list)
    return


class RelationSystem(Component):
    implements(IEnvironmentSetupParticipant)

    @classmethod
    def add_relation(cls, env, relation):
        """Add a relation to the database after doing some validation.

        This method does the actual relation.insert() call of the Relation object.
        Before doing so some validation is performed.

        :param relation: a Relation object which is filled with the relevant data

        In case of validation error a ValidationError is raised.
        If the relation already exist a ResourceExistsError is raised
        """
        if not relation:
            raise ValueError("Relation cannot be None.")

        # Some basics here
        if relation['source'] == relation['dest']:
            raise ValidationError("Validation failed. Source and destination must be different.")

        # Test for cycle
        check_cycle(env, relation)

        # We don't check for duplicates. This will fail with ResourceExistsError
        # in case of duplicates.
        relation.insert()

    # IEnvironmentSetupParticipant methods

    def environment_created(self):
        """Called when a new Trac environment is created."""
        self.upgrade_environment()

    def environment_needs_upgrade(self):
        """Called when Trac checks whether the environment needs to be
        upgraded.

        Should return `True` if this participant needs an upgrade to
        be performed, `False` otherwise.

        :since 1.1.2: the `db` parameter is deprecated and will be removed
                      in Trac 1.3.1. A database connection should instead be
                      obtained using a context manager.
        """
        self.log.info("Checking TracRelations upgrade status")
        dbm = DatabaseManager(self.env)
        db_installed_version = dbm.get_database_version(db_version_key)
        #delete_relations_table(self.env)
        #dbm.create_tables(table)
        return db_installed_version < db_version

    def upgrade_environment(self):
        """Actually perform an environment upgrade.

        Implementations of this method don't need to commit any
        database transactions. This is done implicitly for each
        participant if the upgrade succeeds without an error being
        raised.

        However, if the `upgrade_environment` consists of small,
        restartable, steps of upgrade, it can decide to commit on its
        own after each successful step.

        :since 1.1.2: the `db` parameter is deprecated and will be removed
                      in Trac 1.3.1. A database connection should instead be
                      obtained using a context manager.
        """
        self.log.info("Installing TracRelations database schema")
        with self.env.db_transaction as db:
            cursor = db.cursor()
            cursor.execute(table)

        dbm = DatabaseManager(self.env)

        #dbm.create_tables([table])
        db_installed_version = 1
        dbm.set_database_version(db_installed_version, db_version_key)
