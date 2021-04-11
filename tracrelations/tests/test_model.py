# -*- coding: utf-8 -*-
#
# Copyright (C) 2021 Cinc
#
# License: 3-clause BSD
#
import unittest
from trac.resource import ResourceExistsError
from trac.test import EnvironmentStub
from tracrelations.api import RelationSystem
from tracrelations.model import Relation

from tracrelations.tests.util import revert_schema


class TestRelationModel(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(default_data=True,
                                   enable=["trac.*", "tracrelations.*"])
        self.plugin = RelationSystem(self.env)
        self.config = self.env.config
        with self.env.db_transaction as db:
            revert_schema(self.env)
            self.plugin.upgrade_environment()

    def tearDown(self):
        self.env.reset_db()

    def _add_relations(self):
        rel_data = (('ticket', '1', '2', 'rel1'),
                    ('ticket', '1', '3', 'rel1'),
                    ('wiki', 'FooPage', 'BarPage', 'relation'),
                    ('wiki', 'BarPage', 'BazPage', 'relation'),
                    ('ticket', '3', '4', 'rel2'),
                    ('ticket', '1', '4', 'rel2'))
        for item in rel_data:
            relation = Relation(self.env, *item)
            relation.insert()

    def test_relation(self):
        self._add_relations()
        rel = Relation(self.env, 'ticket', '1', '3', 'rel1')
        self.assertTrue(rel.exists)
        self.assertEqual(2, rel.id)

    def test_relation_int(self):
        self._add_relations()
        rel = Relation(self.env, 'ticket', 1, 3, 'rel1')
        self.assertTrue(rel.exists)
        self.assertEqual(2, rel.id)

    def test_relation_by_id(self):
        self._add_relations()
        rel = Relation(self.env, relation_id=3)
        self.assertTrue(rel.exists)
        self.assertEqual(3, rel.id)
        self.assertEqual('FooPage', rel['source'])

    def test_duplicate(self):
        self._add_relations()
        rel_data = ('ticket', '1', '2', 'rel1')

        relation = Relation(self.env, *rel_data)
        self.assertRaises(ResourceExistsError, relation.insert)

    def test_insert(self):
        def fill_data(rel):
            rel['source'] = '1'
            rel['dest'] = '2'
            rel['type'] = 'relation'

        relation = Relation(self.env, 'ticket')
        self.assertFalse(relation.exists)

        # All relation fields must have a value
        self.assertRaises(ValueError, relation.insert)

        # With proper values insert() must succeed
        fill_data(relation)
        relation.insert()
        self.assertTrue(relation.exists)
        self.assertEqual(1, relation.id)

        # Try to insert the same data -> ValueError
        relation = Relation(self.env, 'ticket')
        fill_data(relation)
        self.assertRaises(ValueError, relation.insert)
        self.assertFalse(relation.exists)

        # Try again with altered 'dest'
        relation['dest'] = '3'
        relation.insert()
        self.assertEqual(2, relation.id)

    def test_select(self):
        self._add_relations()
        # Query all
        rels = list(Relation.select(self.env))
        self.assertEqual(6, len(rels))

        # Filter by realm
        rels = list(Relation.select(self.env, 'wiki'))
        self.assertEqual(2, len(rels))

        # Filter by realm and source
        rels = list(Relation.select(self.env, 'wiki', src='1'))
        self.assertEqual(0, len(rels))
        rels = list(Relation.select(self.env, 'ticket', src='1'))
        self.assertEqual(3, len(rels))

        # Filter by realm and dest
        rels = list(Relation.select(self.env, 'ticket', dest='3'))
        self.assertEqual(1, len(rels))

    def test_save_changes_missing_field(self):
        self._add_relations()

        # All fields must be non-empty
        for field in ('realm', 'source', 'dest', 'type'):
            rels = list(Relation.select(self.env))
            rel = rels[0]
            rel[field] = ''
            self.assertRaises(ValueError, rel.save_changes)

    def test_save_changes(self):
        self._add_relations()

        for field in ('realm', 'source', 'dest', 'type'):
            rels = list(Relation.select(self.env))
            rel = rels[0]
            self.assertNotEqual('foo', rel[field])
            rel[field] = 'foo'
            rel.save_changes()

            rels = list(Relation.select(self.env))
            rel = rels[0]
            self.assertEqual('foo', rel[field])

    def test_delete(self):
        self._add_relations()

        # Filter by realm and dest
        rels = list(Relation.select(self.env, 'ticket', dest='3'))
        self.assertEqual(1, len(rels))

        rel = rels[0]
        saved_id = rel.id
        rel.delete()
        rels = list(Relation.select(self.env, 'ticket', dest='3'))
        self.assertEqual(0, len(rels))

        rels = list(Relation.select(self.env))
        self.assertEqual(5, len(rels))
        for rel in rels:
            self.assertNotEqual(saved_id, rel.id)


if __name__ == '__main__':
    unittest.main()
