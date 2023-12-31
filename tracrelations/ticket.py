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
from trac.resource import get_resource_url, ResourceExistsError, ResourceNotFound
from trac.ticket.api import ITicketChangeListener, ITicketManipulator, TicketSystem
from trac.ticket.model import Ticket
from trac.util.html import tag
from trac.util.text import to_unicode
from trac.util.translation import _
from trac.web.api import IRequestFilter, IRequestHandler
from trac.web.chrome import add_notice, add_script, add_script_data, add_stylesheet, add_warning, Chrome,\
    ITemplateProvider, web_context
from trac.wiki.formatter import format_to_html, format_to_oneliner

from .api import RelationSystem, ValidationError
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

RELDATA_FIELD = 'relationdata'  # ticket custom field name for relation data handling


class TktRelation(Relation):
    """Subclass for tickets with special rendering of relations"""

    BLOCKING = 'blocking'
    RELATION = 'relation'
    PARENTCHILD = 'parentchild'
    DUPLICATE = 'duplicate'

    # Provide user friendly labels
    relations = {
                 BLOCKING: (_("is blocking"), _("is blocked by")),
                 # BLOCKING: (_("blockiert"), _("wird blockiert von")),
                 RELATION: (_("relates to"), _("is related to")),
                 PARENTCHILD: (_("is parent of"), _("is child of")),
                 DUPLICATE: (_("is duplicate of"), _("is duplicated by"))
                }

    def render(self, data):
        """Overriden rendering method mainly returning wiki text for a relation.

        :param data: a dict holding at least: {'req': req} the current Request
        :return wiki text for this relation. If the data dict contains 'format': 'html'
                then HTML Markup is returned.
        """
        req = data.get('req')
        render_format = data.get('format', 'wiki')
        reverse = 1 if 'render_reverse' in self.values else 0
        if not req:
            return ''

        ctxt = web_context(req)
        reltype = self.values['type']

        typelbl = self.relations.get(reltype, (reltype, reltype))[reverse]

        fdata = {'src': self.values['source'],
                 'dest': self.values['dest'],
                 'typelbl': typelbl
                 }
        if not reverse:
            wiki = u"!#{src} ''{typelbl}'' #{dest}".format(**fdata)
        else:
            wiki = u"!#{dest} ''{typelbl}'' #{src}".format(**fdata)

        if render_format == 'wiki':
            return wiki
        else:
            label = format_to_oneliner(self.env, ctxt, wiki)
            return tag.span(label, class_="relation")


class TicketRelations(Component):
    """Relations of different types for tickets.

    This plugin uses the {{{RelationSystem}}} to provide the following ticket relations:

    * simple relations between tickets without any special semantics ({{{relates to}}})
    * allow a ticket to {{{block}}} another ticket
    * specify {{{parent -> child}}} relationships
    * {{{duplicate}}} tickets

    The plugin adds the relationship information to the ticket properties box when
    a ticket page is shown and allows to manage relations between tickets.

    For {{{blocked}}} tickets it makes sure that a ticket can't be resolved as long
    as any blocking ticket is still open.

    {{{Parent -> child}}} relationships don't get any special handling here. There is an
    additional plugin for that.

    When resolving a ticket as a duplicate the user may input a ticket number and
    a {{{duplicate}}} relation is automatically created.

    === Configuration
    It is necessary to create a ticket-custom field {{{relationdata}}}. This field will not
    be shown on the ticket page but is needed for internal use.
    {{{#!ini
    [ticket-custom]
    relationdata = text
    }}}
    """
    implements(ITicketChangeListener, ITicketManipulator, ITemplateProvider, IRequestFilter, IRequestHandler)

    realm = TicketSystem.realm

    # ITicketManipulator methods

    def prepare_ticket(self, req, ticket, fields, actions):
        """Not currently called, but should be provided for future
        compatibility."""
        pass

    def validate_ticket(self, req, ticket):
        """Validate ticket properties when creating or modifying.

        Must return a list of `(field, message)` tuples, one for each problem
        detected. `field` can be `None` to indicate an overall problem with the
        ticket. Therefore, a return value of `[]` means everything is OK."""

        if ticket['status'] == 'closed':
            # Check for ticket blocking.
            block_msg = _("This ticket is blocked. It can't be resolved while ticket #{blocktkt} is still open.")
            rels = Relation.select(self.env, realm=self.realm, dest=ticket.id, reltype='blocking')
            for rel in rels:
                tkt = Ticket(self.env, rel['source'])
                if tkt['status'] != 'closed':
                    yield None, block_msg.format(blocktkt=rel['source'])

            # Check parent child relationship. Ypu only can close a parent when the child(ren) is(are) closed.
            child_msg = _("This ticket is a parent. It can't be resolved while ticket #{childtkt} is still open.")
            rels = Relation.select(self.env, realm=self.realm, src=ticket.id, reltype='parentchild')
            for rel in rels:
                tkt = Ticket(self.env, rel['dest'])
                if tkt['status'] != 'closed':
                    yield None, child_msg.format(childtkt=rel['dest'])

        if ticket['resolution'] == 'duplicate':
            tkt_id = ticket['relationdata'].strip('# ')
            try:
                tkt = Ticket(self.env, tkt_id)
            except ResourceNotFound:
                yield None, _("Ticket %(id)s does not exist.", id=tkt_id)

    def validate_comment(self, req, comment):
        """Validate ticket comment when appending or editing.

        Must return a list of messages, one for each problem detected.
        The return value `[]` indicates no problems.
        """
        return []

    # ITicketChangeListener methods

    def ticket_changed(self, ticket, comment, author, old_values):
        """Called when a ticket is modified.

        `old_values` is a dictionary containing the previous values of the
        fields that have changed.
        """

        if 'resolution' in old_values:  # and ticket['relationdata']:
            tkt_id = ticket['relationdata'].strip('# ')
            if ticket['resolution'] == 'duplicate':
                rel = Relation(self.env, 'ticket', src=ticket.id,
                               dest=tkt_id, type=TktRelation.DUPLICATE)
                RelationSystem(self.env).add_relation(rel)

        # Remove changes regarding the hidden 'relationdata' field. Otherwise we get
        # change messages in the history or when previewing some ticket changes.
        with self.env.db_transaction as db:
            db("DELETE FROM ticket_change WHERE ticket=%s AND field=%s", (ticket.id, 'relationdata'))
            db("DELETE FROM ticket_custom WHERE ticket=%s AND name=%s", (ticket.id, 'relationdata'))

    def ticket_created(self, ticket):
        """Called when a ticket is created."""
        # Remove relationdata from database.
        with self.env.db_transaction as db:
            db("DELETE FROM ticket_custom WHERE ticket=%s AND name=%s", (ticket.id, 'relationdata'))

    def ticket_deleted(self, ticket):
        pass

    def ticket_comment_modified(self, ticket, cdate, author, comment, old_comment):
        """Called when a ticket comment is modified."""
        pass

    def ticket_change_deleted(self, ticket, cdate, changes):
        """Called when a ticket change is deleted.

        `changes` is a dictionary of tuple `(oldvalue, newvalue)`
        containing the ticket change of the fields that have changed."""
        pass

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
        """Create wiki text of all relations to be rendered in the ticket property box.

        :param req: the current Request object
        :param ticket: the currently diplayed ticket. A Trac Ticket object
        :return wikitext, have_relations. The former is Trac wiki text, the latter is True if this
                ticket as any relations.

        'have_relations' is used to decide later on if we show an 'add' button or a 'modify' button.

        Wiki text is used for rendering, because this will automatically resolve ticket ids like #2
        to valid links and we can easily format the output using all the Trac magic like bold, italic
        or WikiProcessors.
        """
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
        is_start = sorted(TktRelation.select(self.env, 'ticket', src=ticket.id), key=lambda k: k['type'])
        links = [rel.render(data) for rel in is_start]

        # Reverse links
        is_end = sorted(TktRelation.select(self.env, 'ticket', dest=ticket.id), key=lambda k: k['type'])
        for rel in is_end:
            rel['render_reverse'] = True
        rev_links = [rel.render(data) for rel in is_end]

        # This is added to the headers as direction indicators
        aright = '` %s `' % Relation.arrow_right if is_start else ''
        aleft = '` %s (reverse) `' % Relation.arrow_left if is_end else ''

        wiki = table_tmpl % (aright, '[[BR]]'.join(links),
                             aleft, '[[BR]]'.join(rev_links))
        return wiki, any((is_end, is_start))

    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, metadata=None):

        if data:
            if template == 'ticket.html':
                tkt = data.get('ticket')
                if tkt:
                    have_links = False
                    if 'fields' in data:
                        # Create a temporary field for display only
                        tkt.values['relations'], have_links = self.create_relations_wiki(req, tkt)  # Activates field
                        data['fields'].append({
                            'name': 'relations',
                            'label': 'Relations',
                            'type': 'textarea',  # Full row
                            'format': 'wiki'
                        })

                    filter_lst = []

                    # Prepare the 'modify' button and manage dialog div for jquery-ui.
                    xform = JTransformer('table.properties #h_relations')
                    filter_lst.append(xform.prepend(self.create_relation_manage_form(tkt, have_links)))
                    xform = JTransformer('div#content')
                    filter_lst.append(xform.append(self.create_manage_relations_dialog()))

                    # Prepare the 'duplicate' input field
                    if tkt.exists:
                        field = data['fields'].by_name('relationdata')
                        if field:
                            field['label'] = _("Duplicate of")
                        xform = JTransformer('#action_resolve_resolve_resolution')
                        filter_lst.append(xform.after('<span style="display: none" id="tktrel-duplicate-id"> of '
                                                      '<input type="text" value="" id="tktrel-id-input"'
                                                      'name="field_relationdata" size="7"/></span>'))

                    add_script_data(req, {'tktrel_filter': filter_lst,
                                          'tktrel_manageurl': './{tkt}/relations?format=fragment'.format(tkt=tkt.id)})
                    add_stylesheet(req, 'ticketrelations/css/ticket_relations.css')
                    add_script(req, 'ticketrelations/js/ticket_relations.js')
                    Chrome(self.env).add_jquery_ui(req)
            elif template == 'ticket_preview.html':
                # Make sure we have a nice label in the property changes box and the prview area
                label = _("Duplicate of")
                if 'change_preview' in data:
                    # That's the properties changes box
                    field = data['change_preview']['fields'].get('relationdata')
                    if field:
                        field['label'] = label
                # That's the ticket box at the top.
                # Unconditional change the label here because 'relationdata' may
                # not be in the changed fields dict
                field = data['fields'].by_name('relationdata')
                if field:
                    # Show field only if resolution is set to 'duplicate'
                    if data.get('change_preview'):
                        resolution = data['change_preview']['fields'].get('resolution')
                        if not resolution or resolution.get('new') != 'duplicate':
                            field['skip'] = True
                    field['label'] = label

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
                    RelationSystem(self.env).add_relation(rel)
                except (ValueError, ValidationError, ResourceExistsError) as e:
                    add_warning(req, e)
                else:
                    txt = u"#{src} {arrow} #{dest}".format(src=rel['source'], dest=rel['dest'], arrow=rel.arrow_both)
                    add_notice(req, "Relation %s added." % txt)
            elif req.args.get('remove-relation'):
                sel = req.args.getlist('sel')
                for relid in sel:
                    rel = TktRelation(self.env, relation_id=relid)
                    # Relation.delete_relation_by_id(self.env, relid)
                    RelationSystem(self.env).delete_relation(rel)
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

        is_end = sorted(TktRelation.select(self.env, 'ticket', dest=tkt.id), key=lambda k: k['type'])
        for rel in is_end:
            rel['render_reverse'] = True

        is_start = sorted(TktRelation.select(self.env, 'ticket', src=tkt.id), key=lambda k: k['type'])

        data = {'ticket': tkt,
                'ticket_url': get_resource_url(self.env, tkt.resource, req.href),
                'fragment': is_fragment,
                'is_start': is_start,
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
