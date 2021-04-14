# -*- coding: utf-8 -*-
#
# Copyright (C) 2021 Cinc
#
# License: 3-clause BSD
#
import unittest
from trac.resource import ResourceExistsError
from trac.test import EnvironmentStub
from tracrelations.api import RelationSystem, ValidationError
from tracrelations.model import Relation

from tracrelations.tests.util import revert_schema


class TestRelationSystem(unittest.TestCase):

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
            self.plugin.add_relation(relation)

    def test_add_relation(self):
        """That's basically the same test as done for the model class"""
        self._add_relations()
        rel = Relation(self.env, 'ticket', '1', '3', 'rel1')
        self.assertTrue(rel.exists)
        self.assertEqual(2, rel.id)

    def test_validate_distinct_Ends(self):
        rel_data = ('ticket', '1', '1', 'rel1')

        relation = Relation(self.env, *rel_data)
        self.assertRaises(ValidationError, self.plugin.add_relation, relation)

    def test_validate_cycle(self):
        rel_data = (('ticket', '1', '2', 'rel1'),
                    ('ticket', '2', '3', 'rel1'),
                    ('ticket', '3', '4', 'rel1'),
                    ('ticket', '4', '2', 'rel1'))  # <-- close cycle here

        for item in rel_data[:-1]:
            relation = Relation(self.env, *item)
            self.plugin.add_relation(relation)
        relation = Relation(self.env, *rel_data[-1])
        self.assertRaises(ValidationError, self.plugin.add_relation, relation)

    def test_duplicate(self):
        self._add_relations()
        rel_data = ('ticket', '1', '2', 'rel1')

        relation = Relation(self.env, *rel_data)
        self.assertRaises(ResourceExistsError, self.plugin.add_relation, relation)


if __name__ == '__main__':
    unittest.main()
