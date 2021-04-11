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
from trac.util.translation import N_


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

class Relation(AbstractEnum):
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
                        enum.value = unicode(int(enum.value) - 1)
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
    _enum_cls = Relation
    _label = N_("Relation"), N_("Relation")


def delete_relations_table(env):
    dbm = DatabaseManager(env)
    dbm.drop_tables(('relation',))

    with env.db_transaction as db:
        db("DELETE FROM system WHERE name='tracrelations_version'")
        db("DELETE FROM system WHERE name='tracrelation_version'")
        db("DELETE FROM system WHERE name='relation_version'")


class RelationSystem(Component):
    implements(IEnvironmentSetupParticipant)

    # IEnvironmentSetupParticipant methods


    def add_relation(self, relation, validators):
        if not relation:
            pass
        

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
