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
from pkg_resources import get_distribution, parse_version, resource_filename
from trac.admin import IAdminPanelProvider
from trac.config import IntOption
from trac.env import IEnvironmentSetupParticipant
from trac.core import *
from trac.ticket.api import ITicketChangeListener, ITicketManipulator, TicketSystem
from trac.ticket.model import Type
from trac.util.html import tag
from trac.util.text import exception_to_unicode, to_unicode
from trac.util.translation import _
from trac.web.api import IRequestFilter
from trac.web.chrome import ITemplateProvider
from trac.web.chrome import add_notice, add_script, add_script_data, add_stylesheet, add_warning
from trac.wiki.formatter import format_to_oneliner

from tracrelations.api import IRelationChangeListener, RelationSystem
from tracrelations.jtransform import JTransformer
from tracrelations.model import Relation


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


class ChildRelationsAdminPanel(Component):
    """Configure which ticket types allow children, inherited fields for children and more.

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
            yield ('childrelations', _('Relations'), 'types',
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


class ChildTicketsModule(Component):
    """Component which inserts the child ticket data into the ticket page"""

    implements(IRelationChangeListener, IRequestFilter, ITemplateProvider, ITicketChangeListener,
               ITicketManipulator)

    max_view_depth = IntOption('Relations-child', 'max_view_depth', default=3,
                               doc="Maximum depth of child ticket tree shown on the ticket page.")

    # IRequestFilter methods

    def pre_process_request(self, req, handler):

        return handler

    def post_process_request(self, req, template, data, content_type):

        if req.path_info == '/newticket':
            pass

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
                    buttons = self.create_child_ticket_buttons(req, ticket)

                    if buttons:
                        # xpath: //div[@id="ticket"]
                        xform = JTransformer('div#ticket')
                        filter_lst.append(xform.after(to_unicode(buttons)))

                add_stylesheet(req, 'ticketrelations/css/child_relations.css')
                add_script_data(req, {'childrels_filter': filter_lst})
                add_script(req, 'ticketrelations/js/childrels_jtransform.js')

        return template, data, content_type

    def create_child_ticket_buttons(self, req, ticket):
        """Create the button div holding buttons for creating child tickets."""

        # Are child tickets allowed?
        childtickets_allowed = self.config.getbool('relations-child', 'parent.%s.allow_child_tickets' % ticket['type'])

        if childtickets_allowed and 'TICKET_CREATE' in req.perm(ticket.resource):

            # Always pass these fields, e.g. the parent ticket id
            default_child_fields = (tag.input(type="hidden", name="relationdata", value=str(ticket.id)),)

            # Pass extra fields defined in inherit parameter of parent
            inherited_child_fields = [
                tag.input(type="hidden", name="%s" % field, value=ticket[field]) for field in
                self.config.getlist('childtickets', 'parent.%s.inherit' % ticket['type'])
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

            buttonform = tag.form(tag.p(_("Create New Ticket")),
                                  tag.div(default_child_fields, inherited_child_fields, submit_button_fields),
                                  method="get", action=req.href.newticket(),
                                  class_="child-trelations-form", )
            return to_unicode(buttonform)
        return ''

    # ITicketManipulator methods

    def prepare_ticket(self, req, ticket, fields, actions):
        pass

    def validate_ticket(self, req, ticket):
        """Validate ticket properties when creating or modifying.

        Must return a list of `(field, message)` tuples, one for each problem
        detected. `field` can be `None` to indicate an overall problem with the
        ticket. Therefore, a return value of `[]` means everything is OK."""

        # This custom field is used to transfer data from e.g. a parent ticket
        # to a newly created child ticket. There is no other way to get that information
        # from a req to the created ticket.
        # Clear the custom field so if we reuse it for more than one transfer we
        # don't get any change entries in the ticket history.
        # In the change listener on may use the data from the 'tracrelation' which
        # is not saved in the database.
        # if ticket['relationdata']:
        #     self.log.info('##### have relationdata: %s' % ticket['relationdata'])
        #     ticket['tracrelation'] = ticket['relationdata']
        #   # ticket['relationdata'] = None

        return []

    def validate_comment(self, req, comment):
        return []

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
                           dest=ticket.id, type='parentchild')
            RelationSystem(self.env).add_relation(rel)

    def ticket_deleted(self, ticket):
        pass

    def ticket_comment_modified(ticket, cdate, author, comment, old_comment):
        """Called when a ticket comment is modified."""
        pass

    def ticket_change_deleted(ticket, cdate, changes):
        """Called when a ticket change is deleted.

        `changes` is a dictionary of tuple `(oldvalue, newvalue)`
        containing the ticket change of the fields that have changed."""
        pass

    # IRelationChangeListener methods

    def relation_added(self, relation):
        """Called when a relation was added"""
        # self.log.info('################ Relation added: %s' % repr(relation))
        pass

    def relation_deleted(self, relation):
        """Called when a relation was deleted"""
        pass

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
