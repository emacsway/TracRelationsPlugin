# -*- coding: utf-8 -*-
#
# Copyright (C) 2021 Cinc
#
# License: 3-clause BSD
#
import re
from pkg_resources import resource_filename
from trac.core import Component, implements
from trac.perm import PermissionError
from trac.resource import get_resource_url
from trac.ticket.api import ITicketManipulator, TicketSystem
from trac.ticket.model import Ticket
from trac.util.html import tag
from trac.util.text import to_unicode
from trac.util.translation import _
from trac.web.api import IRequestFilter, IRequestHandler
from trac.web.chrome import add_notice, add_script, add_script_data, add_stylesheet, add_warning, Chrome,\
    ITemplateProvider, web_context
from trac.wiki.formatter import format_to_html, format_to_oneliner

from .api import RelationSystem
from .jtransform import JTransformer
from .model import Relation

try:
    dict.iteritems
except AttributeError:
    # Python 3
    def iteritems(d):
        return iter(d.items())
else:
    # Python 2
    def iteritems(d):
        return d.iteritems()


class TktRelation(Relation):

    relations = {
                 # 'blocking': ('is blocking', 'is blocked by'),
                 'blocking': ('blockiert', 'wird blockiert von'),
                 'relation': ('relates to', 'is related to'),
                 'parentchild': ('is parent of', 'is child of')}

    def render(self, data):
        req = data.get('req')
        format = data.get('format', 'wiki')
        reverse = True if 'reverse' in self.values else False
        if not req:
            return ''

        ctxt = web_context(req)
        reltype = self.values['type']

        idx = 1 if reverse else 0
        typelbl = self.relations.get(reltype, (reltype, reltype))[idx]

        fdata = {'src': self.values['source'],
                 'arrow': '',  # self.arrow_right,
                 'dest': self.values['dest'],
                 'typelbl': typelbl
                 }
        if not reverse:
            wiki = u"!#{src} ''{typelbl}'' #{dest}{arrow}".format(**fdata)
        else:
            fdata['arrow'] = ''  # self.arrow_left
            wiki = u"{arrow}#{src} ''{typelbl}'' !#{dest}".format(**fdata)

        if format == 'wiki':
            return wiki
        else:
            label = format_to_oneliner(self.env, ctxt, wiki)
            return tag.span(label, class_="relation")


class TicketRelations(Component):
    implements(IRequestFilter, IRequestHandler, ITemplateProvider)

    realm = TicketSystem.realm

    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler

    def create_manage_relations_dialog(self):
        tmpl = u"""<div id="manage-rel-dialog" title="Manage Relations" style="display: none">
        <div id="m-r-body"></div>
        </div>"""
        return tmpl

    def create_relation_manage_form(self, ticket, modify=False):
        """Create the 'add'/'modify' button in a form for the relations table of a ticket.

        :param ticket: Trac Ticket object holding the current ticket.
        :param modify: if True show a 'modify' button else an 'add' button
        :return a unicode string.
        """
        templ = u"""<form action="./{tkt}/relations" id="manage-rel-form">
        <div class="inlinebuttons"><input type="submit" value="{modlabel}" name="manage-rel" ></div>
        </form>"""

        return templ.format(tkt=ticket.id, modlabel=_('Modify') if modify else _('Add'))

    def create_relations_wiki(self, req, ticket):
        table_tmpl = """
        {{{#!table class="" style="width: 100%%" 
        {{{#!tr style="vertical-align: top"
        {{{#!th class="th-relation-small"
        %s
        }}}
        {{{#!td class="td-relation"
        %s
        }}}
        {{{#!th class="th-relation"
        %s
        }}}
        {{{#!td class="td-relation"
        %s
        }}}
        }}}
        }}}"""

        data = {'req': req}
        is_start = [rel.render(data) for rel in TktRelation.select(self.env, 'ticket', src=ticket.id)]

        # Reverse links
        is_end = list(TktRelation.select(self.env, 'ticket', dest=ticket.id))
        for rel in is_end:
            rel['reverse'] = True
        rev_links = [to_unicode(rel.render(data)) for rel in is_end]

        # This is added to the headers as direction indicators
        aright = '` %s `' % Relation.arrow_right if is_start else ''
        aleft = '` %s (reverse) `' % Relation.arrow_left if is_end else ''

        wiki = table_tmpl % (aright, '[[BR]]'.join(is_start),
                             aleft, '[[BR]]'.join(rev_links))
        return wiki, any((is_end, is_start))

    def post_process_request(self, req, template, data, metadata=None):

        if template == 'ticket.html' and data:
            tkt = data.get('ticket')
            if tkt:
                have_links = False
                if 'fields' in data:
                    field = data['fields'].by_name('relations')
                    if field:
                        pass
                    else:
                        tkt.values['relations'], have_links = self.create_relations_wiki(req, tkt)  # Activates field
                        data['fields'].append({
                            'name': 'relations',
                            'label': 'Relations',
                            # 'rendered': html,  # format_to_html(self.env, web_context(req, tkt.resource), '== Baz\n' + tst_wiki),
                            # 'editable': False,
                            # 'value': "",
                            'type': 'textarea',  # Full row
                            'format': 'wiki'
                        })

                filter_lst = []

                # Prepare the manage dialog: 'modify' button and dialog div for jquery-ui.
                xform = JTransformer('table.properties #h_relations')
                filter_lst.append(xform.prepend(self.create_relation_manage_form(tkt, have_links)))
                xform = JTransformer('div#content')
                filter_lst.append(xform.append(self.create_manage_relations_dialog()))

                add_script_data(req, {'tktrel_filter': filter_lst,
                                      'tktrel_manageurl': './{tkt}/relations?format=fragment'.format(tkt=tkt.id)})
                add_stylesheet(req, 'ticketrelations/css/ticket_relations.css')
                add_script(req, 'ticketrelations/js/ticket_relations.js')
                Chrome(self.env).add_jquery_ui(req)

        return template, data, metadata

    # IRequestHandler methods

    def match_request(self, req):
        """Check if user opens relation management page/dialog"""
        match = re.match(r'/ticket/([0-9]+)/relations/*$', req.path_info)
        if not match:
            return False

        req.args['id'] = match.group(1)
        return True

    def process_request(self, req):
        """Handle the relation management page and dialog."""
        tkt_id = req.args.get('id')

        if 'TICKET_VIEW' not in req.perm(self.realm, tkt_id):
            raise PermissionError(_("You don't have permission to view this tickets relations."))
        tkt = Ticket(self.env, tkt_id)  # This raises an exception if tkt_id is invalid

        # this is set if we use the JQuery dialog for managing relations
        is_fragment = req.args.get('format')

        if req.method == 'POST':
            req.perm.require("TICKET_MODIFY")

            if req.args.get('add-relation'):
                src = req.args.get('current-tkt')
                dest = req.args.get('other-tkt')
                rel_type = req.args.get('relation-type')
                try:
                    if rel_type[0] == '!':
                        # Reversed relation, means this ticket is the destination
                        rel = Relation(self.env, 'ticket', dest, src, rel_type[1:])
                    else:
                        rel = Relation(self.env, 'ticket', src, dest, rel_type)
                    RelationSystem.add_relation(self.env, rel)
                except ValueError as e:
                    add_warning(req, e)
                else:
                    txt = u"#{src} {arrow} #{dest}".format(src=rel['source'], dest=rel['dest'], arrow=rel.arrow_both)
                    add_notice(req, "Relation %s added." % txt)
            elif req.args.get('remove-relation'):
                sel = req.args.getlist('sel')
                for relid in sel:
                    rel = TktRelation(self.env, relation_id=relid)
                    Relation.delete_relation_by_id(self.env, relid)
                    txt = u"#{src} {arrow} #{dest}".format(src=rel['source'], dest=rel['dest'], arrow=rel.arrow_both)
                    add_notice(req, "Deleted relation %s" % txt)

            if is_fragment:
                req.redirect(get_resource_url(self.env, tkt.resource, req.href))
            else:
                req.redirect(req.href(req.path_info))

        # Prepare data for select control
        rel_options = []
        aright = TktRelation.arrow_right
        aleft = TktRelation.arrow_left
        for key, val in iteritems(TktRelation.relations):
            rel_options.append((key, val[0] + u" " + aright))
            rel_options.append(('!' + key, aleft + u" " + val[1]))

        is_end = list(TktRelation.select(self.env, 'ticket', dest=tkt.id))
        for rel in is_end:
            rel['reverse'] = True

        data = {'ticket': tkt,
                'ticket_url': get_resource_url(self.env, tkt.resource, req.href),
                'fragment': is_fragment,
                'is_start': list(TktRelation.select(self.env, 'ticket', src=tkt.id)),
                'is_end': is_end,
                'relation_types': rel_options
                }

        if is_fragment:
            return 'ticket_relations_fragment.html', data, {'domain': 'ticketrelations'}
        else:
            return 'manage_ticket_relations.html', data, {'domain': 'ticketrelations'}

    # ITemplateProvider methods

    def get_templates_dirs(self):
        self.log.info(resource_filename(__name__, 'templates'))
        return [resource_filename(__name__, 'templates')]

    def get_htdocs_dirs(self):
        return [('ticketrelations', resource_filename(__name__, 'htdocs'))]
