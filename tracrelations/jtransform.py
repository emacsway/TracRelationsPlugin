# -*- coding: utf-8 -*-
#
# Copyright (C) 2021 Cinc
#
# License: 3-clause BSD
#
class JTransformer(object):
    """Class modelled after the Genshi Transformer class. Instead of an xpath it uses a
       selector usable by jQuery.
       You may use cssify (https://github.com/santiycr/cssify) to convert a xpath to a selector."""

    def __init__(self, xpath):
        self.css = xpath  # xpath must be a css selector for jQuery

    def after(self, html):
        return {'pos': 'after', 'css': self.css, 'html': html}

    def before(self, html):
        return {'pos': 'before', 'css': self.css, 'html': html}

    def prepend(self, html):
        return {'pos': 'prepend', 'css': self.css, 'html': html}

    def append(self, html):
        return {'pos': 'append', 'css': self.css, 'html': html}

    def remove(self):
        return {'pos': 'remove', 'css': self.css, 'html': ''}

    def replace(self, html):
        return {'pos': 'replace', 'css': self.css, 'html': html}
