# -*- coding: utf-8 -*-
#
# Copyright (C) Mark Ryan
# Copyright (C) Ryan J Ollos <ryan.j.ollos@gmail.com>
# Copyright (C) 2021 Cinc
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.
#
from pkg_resources import resource_filename
from trac.admin import IAdminPanelProvider
from trac.cache import cached
from trac.config import IntOption
from trac.core import *
from trac.ticket.api import ITicketChangeListener, TicketSystem
from trac.ticket.model import Ticket, Type
from trac.util.html import tag
from trac.util.text import exception_to_unicode, to_unicode
from trac.util.translation import _
from trac.web.api import IRequestFilter
from trac.web.chrome import ITemplateProvider
from trac.web.chrome import add_notice, add_script, add_script_data, add_stylesheet, add_warning, Chrome
from trac.wiki.formatter import format_to_html, format_to_oneliner

from tracrelations.api import IRelationChangeListener, RelationSystem
from tracrelations.jtransform import JTransformer
from tracrelations.model import Relation
from tracrelations.ticket import TktRelation


INDENT_PERCENT = 3  # the indentation for the child ticket tree items


def _save_config(config, req, log):
    """Try to save the config, and display either a success notice or a
    failure warning.
    """
    try:
        config.save()
        add_notice(req, _('Your changes have been saved.'))
    except Exception as e:
        log.error('Error writing to trac.ini: %s', exception_to_unicode(e))
        add_warning(req, _('Error writing to trac.ini, make sure it is '
                           'writable by the web server. Your changes have not '
                           'been saved.'))


class ChildTicketRelationsAdminPanel(Component):
    """Configure which ticket types allow children at all, inherited fields for children and more.

    All the settings may be controlled from the admin pages. They are saved
    in ''trac.ini'' as shown below.

    The following global settings are available:
    [[TracIni(relations-child)]]

    You may specify features for each ticket type. In this example the configuration
    is for tickets of type {{{defect}}}:
    {{{#!ini
    [relations-child]
    parent.defect.allow_child_tickets = True
    parent.defect.inherit = description,milestone,summary,project,version
    parent.defect.restrict_child_type = defect,enhancement
    parent.defect.table_headers = status,project,summary
    }}}
     parent.<type>.allow_child_tickets = True|False:: if child tickets are allowed for this parent ticket type
     parent.<type>.inherit = fieldname 1, fieldname 2, ...:: specify the ticket fields which should be copied to the child
     parent.<type>.restrict_child_type = type 1, type 2, ...:: allow these types ase new child ticket types
     parent.<type>.table_headers = fieldname 1, fieldname 2, ...:: the table headers to be shown for child tickets
    """

    implements(IAdminPanelProvider, ITemplateProvider)

    # IAdminPanelProvider methods

    def get_admin_panels(self, req):
        if 'TICKET_ADMIN' in req.perm('admin', 'childrelations/types'):
            yield ('childrelations', _('Ticket Relations'), 'types',
                   _('Parent Types'))

    def render_admin_panel(self, req, cat, page, parenttype):

        # Only for ticket admins.

        req.perm('admin', 'childrelations/types').require('TICKET_ADMIN')

        field_names = TicketSystem(self.env).get_ticket_field_labels()

        # Detail view?
        if parenttype:
            if req.method == 'POST':
                allow_child_tickets = \
                    req.args.get('allow_child_tickets')
                self.config.set('relations-child',
                                'parent.%s.allow_child_tickets'
                                % parenttype,
                                allow_child_tickets)

                headers = req.args.getlist('headers')
                self.config.set('relations-child',
                                'parent.%s.table_headers' % parenttype,
                                ','.join(headers))

                restricted = req.args.getlist('restricted')
                self.config.set('relations-child',
                                'parent.%s.restrict_child_type' % parenttype,
                                ','.join(restricted))

                inherited = req.args.getlist('inherited')
                self.config.set('relations-child',
                                'parent.%s.inherit' % parenttype,
                                ','.join(inherited))

                _save_config(self.config, req, self.log),
                req.redirect(req.href.admin(cat, page))

            # Convert to object.
            parenttype = ParentType(self.config, parenttype, field_names)

            data = {
                'view': 'detail',
                'parenttype': parenttype,
                'table_headers': self._headers(parenttype),
                'parent_types': self._types(parenttype),
                'inherited_fields': self._inherited(parenttype),
                'field_names': TicketSystem(self.env).get_ticket_field_labels()
            }
        else:
            data = {
                'view': 'list',
                'base_href': req.href.admin(cat, page),
                'ticket_types': [ParentType(self.config, p, field_names) for p in self.ticket_types],
                'field_names': TicketSystem(self.env).get_ticket_field_labels()
            }

        # Add our own styles for the ticket lists.
        add_stylesheet(req, 'ticketrelations/css/child_relations.css')

        return 'admin_childrelations.html', data

    # ITemplateProvider methods

    def get_templates_dirs(self):
        self.log.info(resource_filename(__name__, 'templates'))
        return [resource_filename(__name__, 'templates')]

    def get_htdocs_dirs(self):
        return [('ticketrelations', resource_filename(__name__, 'htdocs'))]

    # Custom methods

    def _headers(self, ptype):
        """Returns a list of valid headers for the given parent type.
        """
        ticket_fields = [item['name'] for item in TicketSystem(self.env).get_ticket_fields()]
        # Description is always shown so don't allow user to select/deselect it
        headers = [item for item in ticket_fields if item != 'description']
        headers = dict.fromkeys(headers, None)
        headers.update(
            dict.fromkeys(map(lambda x: x.lower(), ptype.table_headers),
                          'checked'))
        return headers

    def _inherited(self, ptype):
        """Returns a list of inherited fields.
        """
        ticket_fields = [item['name'] for item in TicketSystem(self.env).get_ticket_fields()]
        inherited = dict.fromkeys(ticket_fields, None)
        inherited.update(
            dict.fromkeys(map(lambda x: x.lower(), ptype.inherited_fields),
                          'checked'))
        return inherited

    @property
    def ticket_types(self):
        return [item.name for item in Type.select(self.env)]

    def _types(self, ptype):
        """
        Return a dictionary with info as to whether the parent type
        is already selected as an available child type.
        """
        types = dict.fromkeys(x for x in self.ticket_types)
        types.update(dict.fromkeys(
            map(lambda x: x.lower(), ptype.restrict_to_child_types),
            'checked'))
        return types


class ChildTicketRelations(Component):
    """Component for child ticket handling. Supplements the TicketRelations plugin.

    The {{{TicketRelations}}} plugin provides basic features with regard to {{{parent -> child}}}
    relationships like allowing to manage those relations. This plugin adds some more:

    * creation of child tickets from the ticket page, thus the parent->child relationship is
      automatically maintained
    * have different child ticket types for different ticket types
    * show a (foldable) child ticket tree on the ticket page
    * allow to customize the shown ticket data in the child ticket tree

    For feature customization is an admin panel available. See {{{ChildTicketRelationsAdminPanel}}} for
    more information.
    """

    implements(IRelationChangeListener, IRequestFilter, ITemplateProvider, ITicketChangeListener)

    max_view_depth = IntOption('relations-child', 'max_view_depth', default=3,
                               doc="Maximum depth of child ticket tree shown on the ticket page.")

    # IRequestFilter methods

    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):

        if data and template in ('ticket.html', 'ticket_box.html'):

            ticket = data.get('ticket')

            if ticket:
                filter_lst = []
                parent_id = ticket['relationdata']
                rendered_parent = format_to_oneliner(self.env, data['context'], '#%s' % parent_id)
                if 'fields' in data:
                    # When creating a newticket show read-only fields with an appropriate label for
                    # the custom field 'relationdata'.
                    # When showing a ticket after creation hide the custom field.
                    #
                    # The custom  field holds the parent ticket id and is needed so the
                    # parent id ends up in the change listener 'ticket_created()' where we can create
                    # the relation in the database.
                    field = data['fields'].by_name('relationdata')
                    if field:
                        if ticket.exists or not parent_id:
                            field['skip'] = True
                        else:
                            field['rendered'] = rendered_parent
                            field['label'] = _("Child of")
                            # replace the input field with hidden one and text so the user can't change the parent.
                            xform = JTransformer('input#field-relationdata')
                            filter_lst.append(xform.replace('<input type="hidden" id="field-relationdata" '
                                                            'name="field_relationdata" '
                                                            'value="{tkt}"/>'.format(tkt=parent_id) +
                                                            to_unicode(rendered_parent)))

                if ticket.exists:
                    xform = JTransformer('div#ticket')
                    tree = self.create_childticket_tree_html(data, ticket)
                    filter_lst.append(xform.after(to_unicode(tree)))

                    buttons = self.create_child_ticket_buttons(req, ticket)
                    if buttons:
                        # xpath: //div[@id="ticket"]
                        xform = JTransformer('div#ticket')
                        filter_lst.append(xform.after(to_unicode(buttons)))

                add_stylesheet(req, 'ticketrelations/css/child_relations.css')
                add_script_data(req, {'childrels_filter': filter_lst})
                add_script(req, 'ticketrelations/js/childrels_jtransform.js')

        return template, data, content_type

    @cached
    def childtickets(self):
        children = {}
        for rel in Relation.select(self.env, 'ticket', reltype=TktRelation.PARENTCHILD):
            children.setdefault(int(rel['source']), []).append(int(rel['dest']))
        return children

    def create_childticket_tree_html(self, data, ticket):

        # Modify ticket.html with sub-ticket table, create button, etc...
        # As follows:
        # - If ticket has no child tickets and child tickets are NOT allowed then skip.
        # - If ticket has child tickets and child tickets are NOT allowed (ie. rules changed or ticket type
        #   changed after children were assigned),
        #   print list of tickets but do not allow any tickets to be created.
        # - If child tickets are allowed then print list of child tickets or 'No Child Tickets' if none are
        #   currently assigned.
        if ticket and ticket.exists:
            def indented_table(tkt, treecolumns, indent=0):
                """Create a table from the ticket tkt which may be indented.

                :param tkt:            a Trac ticket
                :param treecolumns:    list of column names
                :param indent:         level of indentation for this table. Int value starting with 0.

                The table has a header holding the items described by treecolums. Next row
                are the data items matching the header. The following row spans all columns
                and holds the ticket description.
                If the description contains wiki data it will be porperly parsed and inserted
                into the result.
                For each level of indentation (0, 1, 2, ...) the table will be indented by a
                percentage defined as INDENT_PERCENT (usually 3..5%).
                """
                # Admin may have removed a custom field still in the list of table headers
                treecolumns = [col for col in treecolumns if col in field_names]
                desc = format_to_html(self.env, data['context'], tkt['description'])

                if tkt['status'] == 'closed':
                    cls = "listing childrel-table closed"
                else:
                    cls = "listing childrel-table"

                # Return the table
                return tag.table(
                    tag.thead(
                        tag.tr(tag.th("Ticket", class_="id"),
                               [tag.th(field_names[col], class_=col) for col in treecolumns]
                               )
                    ),
                    tag.tbody(self._table_row(data, tkt, treecolumns, field_format),
                              tag.tr(
                                  tag.td(desc, class_="description", colspan="%s" % str(1 + len(treecolumns))),
                                  class_="even",
                              ),
                              tag.tr(
                                  tag.td(_("(Rest of the child ticket tree is hidden)"),
                                         class_="system-message notice", colspan="%s" % str(1 + len(treecolumns))),
                                  class_="even",
                              ) if tkt.max_view else None,
                              ),
                    class_=cls,
                    style="margin-left: %s%%; width : %s%%" % (str(indent * INDENT_PERCENT),
                                                               str(100 - indent * INDENT_PERCENT)),
                )

            def create_table_tree(tickets):
                """
                    Create a tree of ticket tables from the tickets in the list tickets.
                """
                childtree = []
                for tkt in tickets:
                    if tkt.indent == 1:
                        div = tag.div(class_="childrel-tables")  #  note the trailing s in the class
                        childtree.append(div)

                    treecolumns = self.config.getlist('relations-child', 'parent.%s.table_headers' % tkt['type'],
                                                      default=['summary', 'owner'])
                    # The description will always be displayed in separate td no matter whats defined in the ini
                    if 'description' in treecolumns:
                        treecolumns.remove('description')

                    div.append(indented_table(tkt, treecolumns, tkt.indent - 1))
                return childtree

            def indent_children(tkt, all_tickets, indent=0):
                tkt.max_view = False
                if tkt.id in self.childtickets:
                    indent += 1
                    for child in self.childtickets[tkt.id]:
                        if indent > self.max_view_depth:
                            tkt.max_view = True  # Mark that we don't want to show more children
                            return
                        child = Ticket(self.env, child)
                        child.indent = indent
                        all_tickets.append(child)
                        indent_children(child, all_tickets, indent)

            # Are child tickets allowed?
            childtickets_allowed = self.config.getbool('relations-child', 'parent.%s.allow_child_tickets' % ticket['type'])

            # Are there any child tickets to display?
            childtickets = [Ticket(self.env, n) for n in self.childtickets.get(ticket.id, [])]
            # (tempish) fix for #8612 : force sorting by ticket id
            childtickets = sorted(childtickets, key=lambda t: t.id)

            # If there are no childtickets and the ticket should not
            # have any child tickets, we can simply drop out here.
            if not childtickets_allowed and not childtickets:
                return ''

            field_names = TicketSystem(self.env).get_ticket_field_labels()
            # We need this to decide if we should wikify a field in the child table
            field_format = {item['name']: item.get('format', None) for item in TicketSystem(self.env).get_ticket_fields()}
            # The additional section on the ticket is built up of (potentially) three parts: header, ticket table, buttons. These
            # are all 'wrapped up' in a 'div' with the 'attachments' id (we'll just pinch this to make look and feel consistent with any
            # future changes!)
            snippet = tag.div(id="ct-children", class_="collapsed")  # foldable child tickets area

            # Our 'main' display consists of divs.
            # buttonform = tag.div()
            treediv = tag.div()  # This is for displaying the child ticket tree

            # Test if the ticket has children: If so, then list in pretty table.
            if childtickets:
                all_tickets = []  # We need this var for the recursive _indent_children() collecting the tickets
                indent_children(ticket, all_tickets)
                # This is a list of whole trees of child->grandchild->etc
                # for each child ticket
                treediv = create_table_tree(all_tickets)

            snippet.append(tag.h3("Child Ticket Tree ",
                                  tag.span('(%s)' % len(childtickets), class_="trac-count"),
                                  class_="foldable"))
            if childtickets:
                snippet.append(tag.div(treediv, id="childrelations"))

            return snippet
        else:
            return ''

    def _table_row(self, data, ticket, columns, field_format):
        """
        @param data: data dictionary given to the ticket page
        @param ticket: Ticket object with the data
        @param columns: ticket fields to be shown
        @param field_format: dict with key: name of field, val: type of field
        :param data:
        """
        # Is this too slow or do we run with it here?
        chrome = Chrome(self.env)

        def get_value(field):
            if field in ('owner', 'reporter'):
                return chrome.authorinfo(data['context'].req, ticket[field])
            elif field_format[field] == 'wiki':
                return format_to_oneliner(self.env, data['context'], ticket[field])
            else:
                return ticket[field]

        return tag.tr(
            tag.td(format_to_oneliner(self.env, data['context'], "#%s" % ticket.id)),
            [tag.td(get_value(s), class_=s) for s in columns],
            class_="odd"
        )

    def create_child_ticket_buttons(self, req, ticket):
        """Create the button div holding buttons for creating child tickets.

        :param req: Request object for the ticket page
        :param ticket: Ticket object, guaranteed to exist
        :return unicode string
        """

        # Are child tickets allowed?
        childtickets_allowed = self.config.getbool('relations-child', 'parent.%s.allow_child_tickets' % ticket['type'])

        button_div = tag.div()

        # trac.ini : child tickets are allowed - Set up 'create new ticket' buttons.
        if childtickets_allowed and 'TICKET_CREATE' in req.perm(ticket.resource):

            # Always pass these fields, e.g. the parent ticket id
            default_child_fields = (tag.input(type="hidden", name="relationdata", value=str(ticket.id)),)

            # Pass extra fields defined in inherit parameter of parent
            inherited_child_fields = [
                tag.input(type="hidden", name="%s" % field, value=ticket[field]) for field in
                self.config.getlist('relations-child', 'parent.%s.inherit' % ticket['type'])
            ]

            # If child types are restricted then create a set of buttons for the allowed types (This will override 'default_child_type).
            restrict_child_types = self.config.getlist('relations-child',
                                                       'parent.%s.restrict_child_type' % ticket['type'],
                                                       default=[])

            if not restrict_child_types:
                # trac.ini : Default 'type' of child tickets?
                default_child_type = self.config.get('relations-child',
                                                     'parent.%s.default_child_type' % ticket['type'],
                                                     default=self.config.get('ticket', 'default_type'))

                # ... create a default submit button
                if ticket['status'] == 'closed':
                    submit_button_fields = (
                        tag.input(type="submit", disabled="disabled", name="childticket",
                                  value="New Child Ticket", title="Create a child ticket"),
                        tag.input(type="hidden", name="type", value=default_child_type),)
                else:
                    submit_button_fields = (
                        tag.input(type="submit", name="childticket", value="New Child Ticket",
                                  title="Create a child ticket"),
                        tag.input(type="hidden", name="type", value=default_child_type),)
            else:
                if ticket['status'] == 'closed':
                    submit_button_fields = [
                        tag.input(type="submit", disabled="disabled", name="type", value="%s" % ticket_type,
                                  title="Create a %s child ticket" % ticket_type) for ticket_type in
                        restrict_child_types]
                else:
                    submit_button_fields = [tag.input(type="submit", name="type", value="%s" % ticket_type,
                                                      title="Create a %s child ticket" % ticket_type) for
                                            ticket_type in restrict_child_types]

            button_div.append(tag.form(tag.fieldset(tag.legend(_("Create New Child Ticket")),
                                                    tag.div(default_child_fields, inherited_child_fields,
                                                            submit_button_fields)),
                                                    method="get", action=req.href.newticket(),
                                                    class_="child-trelations-form"))
            return to_unicode(button_div)

        # Creation is not allowed for some reason
        # button_div.append(tag.h4(_("Create New Child Ticket")))
        button_div.append(tag.p(_("(Child tickets are disabled for this ticket type "
                                  "or you don't have the necessary permissions to create tickets.)"),
                                class_="help"
                                )
                          )
        return to_unicode(button_div)

    # ITicketChangeListener methods

    def ticket_changed(self, ticket, comment, author, old_values):
        """Called when a ticket is modified.

        `old_values` is a dictionary containing the previous values of the
        fields that have changed.
        """
        pass

    def ticket_created(self, ticket):
        """Called when a ticket is created."""
        # If we are a child ticket than create the relation in the database.
        if ticket['relationdata']:
            rel = Relation(self.env, 'ticket', src=ticket['relationdata'],
                           dest=ticket.id, type=TktRelation.PARENTCHILD)
            RelationSystem(self.env).add_relation(rel)

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

    # IRelationChangeListener methods

    def relation_added(self, relation):
        """Called when a relation was added"""
        if relation['type'] == TktRelation.PARENTCHILD:
            del self.childtickets

    def relation_deleted(self, relation):
        """Called when a relation was deleted"""
        if relation['type'] == TktRelation.PARENTCHILD:
            del self.childtickets

    # ITemplateProvider methods

    def get_templates_dirs(self):
        self.log.info(resource_filename(__name__, 'templates'))
        return [resource_filename(__name__, 'templates')]

    def get_htdocs_dirs(self):
        return [('ticketrelations', resource_filename(__name__, 'htdocs'))]


class ParentType(object):
    def __init__(self, config, name, field_names):
        """
        @param field_names: dict with {name: label} for each ticket field
        """
        self.name = name
        self.config = config
        self.field_names = field_names

    @property
    def allow_child_tickets(self):
        return self.config.getbool('relations-child',
                                   'parent.%s.allow_child_tickets' % self.name,
                                   default=False)

    @property
    def table_headers(self):
        hdrs = self.config.getlist('relations-child',
                                   'parent.%s.table_headers' % self.name,
                                   default=['summary', 'owner'])
        return [col for col in hdrs if col in self.field_names]

    @property
    def restrict_to_child_types(self):
        return self.config.getlist('relations-child',
                                   'parent.%s.restrict_child_type' % self.name,
                                   default=[])

    @property
    def inherited_fields(self):
        return self.config.getlist('relations-child',
                                   'parent.%s.inherit' % self.name,
                                   default=[])

    @property
    def default_child_type(self):
        return self.config.get('relations-child',
                               'parent.%s.default_child_type' % self.name,
                               default=self.config.get('ticket',
                                                       'default_type'))

    @property
    def table_row_class(self):
        """Return a class (enabled/disabled) for the table row - allows it
        to 'look' disabled if not active.
        """
        if self.allow_child_tickets:
            return 'enabled'
        return 'disabled'
