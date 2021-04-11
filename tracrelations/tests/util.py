# -*- coding: utf-8 -*-
#
# Copyright (C) 2021 Cinc
#
# License: 3-clause BSD
#

def revert_schema(env):
    with env.db_transaction as db:
        for table in ('relation',):
            db("DROP TABLE IF EXISTS %s" % db.quote(table))
        db("DELETE FROM system WHERE name='relation_version'")
