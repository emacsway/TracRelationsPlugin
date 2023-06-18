# -*- coding: utf-8 -*-
#
# Copyright (C) 2021 Cinc
#
# License: 3-clause BSD
#
from trac.util.html import tag
from trac.resource import ResourceExistsError

class Relation(object):

    realm = 'relation'
    label = 'relation'
    arrow_both = u"\u2194"
    arrow_right = u"\u2192"
    arrow_left = u"\u2190"

    def __init__(self, env, realm=None, src=None, dest=None, type=None, relation_id=None):
        self.env = env
        self.values = {'realm': realm, 'source': src,
                       'dest': dest, 'type': type}
        self.exists = False
        try:
            self.check_fields()  # This ignores the relation_id
        except ValueError:
            # No complete set of parameters (excluding relation_id)
            # Try to get relation by id. This is used by the management page.
            if relation_id:
                res = Relation._fetch_by_id(self.env, relation_id)
                if res:
                    Relation._assign_values(self, *res)
        else:
            res = list(Relation._fetch_from_db(env, realm, src, dest, type))
            if res:
                self.id = res[0][0]
                self.exists = True

    def __repr__(self):
        val = self.values
        return '<%s %r, %s, %s, %s>' % \
               (self.__class__.__name__, val['realm'], val['source'], val['dest'], val['type'])

    def __getitem__(self, name):
        return self.values.get(name)

    def __setitem__(self, name, value):
        # If we record changes later we have to add code here
        if name in self.values and self.values[name] == value:
            return

        self.values[name] = value

    def __contains__(self, item):
        return item in self.values

    @staticmethod
    def _assign_values(relation, id_, realm, src, dest, reltype):
        relation.id = id_
        relation['realm'] = realm
        relation['source'] = src
        relation['dest'] = dest
        relation['type'] = reltype

        relation.exists = True

    @staticmethod
    def _fetch_from_db(env, realm=None, src=None, dest=None, reltype=None):
        if not realm:
            for res in env.db_query("""SELECT * FROM relation"""):
                yield res
        else:
            sql = "SELECT * FROM relation WHERE realm=%s"
            vals = [realm]
            for item in (('source', src), ('dest', dest), ('type', reltype)):
                if item[1]:
                    sql += " AND %s=%%s" % item[0]
                    vals.append(str(item[1]))

            for res in env.db_query(sql, vals):
                yield res

    @staticmethod
    def _fetch_by_id(env, relation_id):
        for res in env.db_query("SELECT * FROM relation WHERE id=%s", (relation_id,)):
            return res

    @classmethod
    def select(cls, env, realm=None, src=None, dest=None, reltype=None):

        for rel in Relation._fetch_from_db(env, realm, src, dest, reltype):
            relation = cls(env, realm)
            cls._assign_values(relation, *rel)
            yield relation

    def insert(self, when=None):
        self.check_fields()

        val = self.values
        if self.exists:
            raise ResourceExistsError("Relation '%s', '%s', '%s', '%s' already exists." %
                                      (val['realm'], val['source'], val['dest'], val['type']))
        try:
            with self.env.db_transaction as db:
                cursor = db.cursor()
                cursor.execute("""INSERT INTO relation
                                  (realm, source, dest, type)
                                  VALUES (%s,%s,%s,%s)
                                  """, (val['realm'], val['source'],
                                        val['dest'], val['type']))
                self.exists = True
                self.id = db.get_last_id(cursor, 'relation', 'id')
        except self.env.db_exc.IntegrityError:
            raise
            # raise ValueError("Relations must be unique.")

    @staticmethod
    def delete_relation_by_id(env, rel_id):
        if not rel_id:
            raise ValueError("No relation id given.")
        with env.db_transaction as db:
            db("DELETE FROM relation WHERE id=%s", (rel_id,))

    def delete(self):
        assert self.exists, "Cannot delete a new relation"

        with self.env.db_transaction as db:
            db("DELETE FROM relation WHERE id=%s", (self.id,))
            self.exists = False

    def check_fields(self):
        for name in ('realm', 'source', 'dest', 'type'):
            if not self.values[name]:
                raise ValueError("Relation: '%s' can't be empty." % name)

    def save_changes(self):
        assert self.exists, "Cannot update a new relation"

        self.check_fields()

        val = self.values
        with self.env.db_transaction as db:
            db("""UPDATE relation
                  SET realm=%s, source=%s, dest=%s, type=%s
                  WHERE id=%s
               """, (val['realm'], val['source'],
                     val['dest'], val['type'], self.id))

    def render(self, data):
        label = u"%s %s %s (%s)" % (self.values['source'], self.arrow_both,
                                        self.values['dest'], self.values['type'])
                                   # self.label or self.values['type'])

        return tag.span(label, class_="relation")
