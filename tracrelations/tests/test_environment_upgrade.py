# -*- coding: utf-8 -*-
#
# Copyright (C) 2021 Cinc
#
# License: 3-clause BSD
#
import unittest
from trac.test import EnvironmentStub
from tracrelations.api import RelationSystem, tables_v1


class TestEnvironmentUpgrade(unittest.TestCase):

    def setUp(self):
        self.env = EnvironmentStub(default_data=True,
                                   enable=["trac.*", "tracrelations.*"])
        self.plugin = RelationSystem(self.env)

    def test_install_v1(self):
        self.plugin.upgrade_environment()


if __name__ == '__main__':
    unittest.main()
