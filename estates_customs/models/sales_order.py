from odoo import models, fields, api, _, osv
from odoo.exceptions import RedirectWarning, UserError, ValidationError
import html
class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.model
    def create(self, vals):
        user = self.env.user
        allowed_users = user.company_id.approved_level1_by

        if user not in allowed_users:
            allowed_user_names = ', '.join(allowed_users.mapped('name')) or 'No users allowed'
            raise UserError(_(
                "You are not allowed to create Sales Orders.\n\n"
                "Only the following users can create sales:\n%s"
            ) % allowed_user_names)

        record = super().create(vals)
        record._send_new_so_notification_email()
        return record

    def _send_new_so_notification_email(self):
        """Send email notification to selected users when a new Sales Order is created."""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        company = self.company_id
        users = company.to_be_notified

        for user in users:
            if not user.partner_id.email:
                continue

            so_url = f"{base_url}/web#id={self.id}&model=sale.order&view_type=form"
            so_link = f'<a href="{so_url}">Open Sales Order</a>'

            email_values = {
                'subject': _('New Sales Order Created: %s') % self.name,
                'body_html': """
                        <p>Hello %s,</p>
                        <p>A new Sales Order <strong>%s</strong> has been created.</p>
                        <p>
                            <strong>Customer:</strong> %s<br/>
                            <strong>Total:</strong> %s<br/>
                            <strong>Created by:</strong> %s<br/>
                            %s
                        </p>
                        <p>Regards,<br/>Your Odoo System</p>
                    """ % (
                    html.escape(user.name),
                    html.escape(self.name),
                    html.escape(self.partner_id.name or ''),
                    self.amount_total,
                    html.escape(self.create_uid.name),
                    so_link
                ),
                'email_to': user.partner_id.email,
                'auto_delete': True,
                'email_from': self.env.user.email or 'no-reply@yourcompany.com',
            }

            self.env['mail.mail'].create(email_values).send()



    def _get_share_url(self):
        """Generate a shareable URL for this sales order"""
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        url = f"{base_url}/web#id={self.id}&model=sale.order&view_type=form"
        return url
    lpo_number = fields.Char(
        string='LPO Number',
        tracking=True,
        copy=False,
        help='LPO Number from the customer'
    )
    @api.onchange('pricelist_id')
    def _onchange_picking_type_set_pricelist(self):
        """
        When user selects a picking type (warehouse), set its dedicated pricelist on sales order.
        """
        if self.pricelist_id:
            warehouse = self.pricelist_id.warehouse_id
            if warehouse:
                self.warehouse_id = warehouse

    lpo_attachment_ids = fields.Many2many(
        'ir.attachment',
        'sale_order_lpo_rel',
        'sale_order_id',
        'attachment_id',
        string='LPO Attachments',
        help='Attach LPO documents related to this sales order.'
    )

    payment_slip_attachment_ids = fields.Many2many(
        'ir.attachment',
        'sale_order_payment_slip_rel',
        'sale_order_id',
        'attachment_id',
        string='Payment Slip Attachments',
        help='Attach payment slips related to this sales order.'
    )
    approval_status = fields.Selection([
        ('draft', 'Draft'),
        ('pending_level_1', 'Pending Level 1 Approval'),
        ('approved_level_1', 'Approved by Level 1'),
        ('pending_level_2', 'Pending Level 2 Approval'),
        ('approved_level_2', 'Approved by Level 2'),
        ('pending_level_3', 'Pending Level 3 Approval'),
        ('approved', 'Fully Approved'),
        ('rejected', 'Rejected')
    ], string='Approval Status', default='draft',copy=False, tracking=True)

    current_approver_id = fields.Many2one('res.users', string='Current Approver', readonly=True)
    level1_approved_by = fields.Many2one('res.users', string='Level 1 Approved By', readonly=True)
    level2_approved_by = fields.Many2one('res.users', string='Level 2 Approved By', readonly=True)
    level3_approved_by = fields.Many2one('res.users', string='Final Approved By', readonly=True)
    reject_reason = fields.Text("Rejection Reason", readonly=True)

    def action_confirm(self):
        """Override standard confirm to require approval"""
        for order in self:
            if order.approval_status not in ['approved']:
                raise UserError(_("This order must be fully approved before confirming."))
        return super().action_confirm()

    def action_request_approval(self):
        """Submit SO for approval"""
        for order in self:
            if order.state != 'draft':
                raise UserError(_("Only draft orders can be submitted for approval."))

            company = order.company_id
            if not company.approved_level1_by or not company.approved_level2_by or not company.approved_level2_by:
                raise UserError(_("Please configure approvers in Company Settings."))

            order.write({
                'approval_status': 'pending_level_1',
                'current_approver_id': company.approved_level1_by[0].id
            })
            if company.approved_level1_by:
                for data in company.approved_level1_by:
                    # Send Email to Level 1 Approver
                    email_values = {
                        'email_to': data.email,
                        'email_from': self.env.company.email,
                    }
                    custom_values = {
                        'url': self._get_share_url(),
                        'company_name': self.env.company.name,
                        'name':  data.name,
                        'user': self.env.user.name,
                        'date': fields.Date.today(),
                    }
                    template = self.env.ref('estates_customs.email_template_so_approval_all_levels')
                    template.with_context(custom_values).send_mail(order.id,
                                                                   email_values=email_values,force_send=True)

    def action_approve(self):
        self.ensure_one()
        user = self.env.user

        if self.approval_status == 'pending_level_1':
            if user not in self.env.company.approved_level1_by:
                raise UserError(_("You are not authorized to approve at Level 1."))
            self._approve_level1()

        elif self.approval_status == 'pending_level_2':
            if user not in self.env.company.approved_level2_by:
                raise UserError(_("You are not authorized to approve at Level 2."))
            self._approve_level2()

        elif self.approval_status == 'pending_level_3':
            if user not in self.env.company.last_approver:
                raise UserError(_("You are not authorized to approve at Final Level."))
            self._approve_final()

        else:
            raise UserError(_("Invalid approval status."))

    def _approve_level1(self):
        self.write({
            'approval_status': 'approved_level_1',
            'level1_approved_by': self.env.user.id,
            'current_approver_id': False
        })
        # Move to Level 2
        company = self.company_id
        self.write({
            'approval_status': 'pending_level_2',
            'current_approver_id': company.approved_level2_by[0].id
        })

        if company.approved_level2_by:
            for data in company.approved_level2_by:
                email_values = {
                    'email_to': data.email,
                    'email_from': self.env.company.email,
                }
                custom_values = {
                    'url': self._get_share_url(),
                    'company_name': self.env.company.name,
                    'name': data.name,
                    'user': self.env.user.name,
                    'date': fields.Date.today(),
                }
                template = self.env.ref('estates_customs.email_template_so_approval_all_levels')
                template.with_context(custom_values).send_mail(self.id,
                                                               email_values=email_values, force_send=True)


    def _approve_level2(self):
        self.write({
            'approval_status': 'approved_level_2',
            'level2_approved_by': self.env.user.id,
            'current_approver_id': False
        })
        # Move to Level 3
        company = self.company_id
        self.write({
            'approval_status': 'pending_level_3',
            'current_approver_id': company.last_approver[0].id
        })
        if company.last_approver:
            for data in company.last_approver:
                # Send Email to Level 3 Approver
                email_values = {
                    'email_to': data.email,
                    'email_from': self.env.company.email,
                }
                custom_values = {
                    'url': self._get_share_url(),
                    'company_name': self.env.company.name,
                    'name': data.name,
                    'user': self.env.user.name,
                    'date': fields.Date.today(),
                }
                template = self.env.ref('estates_customs.email_template_so_approval_all_levels')
                template.with_context(custom_values).send_mail(self.id,
                                                               email_values=email_values, force_send=True)


    def _approve_final(self):
        self.write({
            'approval_status': 'approved',
            'level3_approved_by': self.env.user.id,
            'current_approver_id': False,
            # 'state': 'sent'  # or 'sale' based on your business flow
        })
        company = self.company_id
        if company.posted_by:
            for data in company.posted_by:
                email_values = {
                    'email_to': data.email,
                    'email_from': self.env.company.email,
                }
                custom_values = {
                    'url': self._get_share_url(),
                    'company_name': self.env.company.name,
                    'name': data.name,
                    'user': self.env.user.name,
                    'date': fields.Date.today(),
                }
                template = self.env.ref('estates_customs.email_template_so_approval_all_levels')
                template.with_context(custom_values).send_mail(self.id,
                                                               email_values=email_values, force_send=True)


    def action_reject(self, reason):
        self.ensure_one()
        self.write({
            'approval_status': 'rejected',
            'reject_reason': reason,
            'current_approver_id': False
        })

        # Optionally send rejection email back to salesperson
        template = self.env.ref('custom_approval_flow.email_template_so_rejected')
        template.send_mail(self.id)

    def action_reset_to_draft(self):
        self.ensure_one()
        self.write({
            'approval_status': 'draft',
            'level1_approved_by': False,
            'level2_approved_by': False,
            'level3_approved_by': False,
            'current_approver_id': False,
            'reject_reason': False,
        })


class StockMove(models.Model):
    _inherit = 'stock.move'
    pass

    remark = fields.Text(string='Remark')
class ProductTemplate(models.Model):
    _inherit = 'product.template'

    weight = fields.Float(string='Weight',required=True)

class ProductProduct(models.Model):
    _inherit = 'product.product'

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        # Prevent quick-create suggestions unless explicitly allowed
        return super()._name_search(name=name, args=args, operator=operator, limit=limit, name_get_uid=name_get_uid)
RESTRICTED_REPORTS =  [
            'estates_customs.report_loading_instruction_template',
            'estates_customs.action_report_loading_instructions_id_card',
            'estates_customs.report_custom_delivery_note_loading_instruction_template',
            'stock.report_deliveryslip', 'stock.report_picking'
]


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, docids, data=None):
        """Override to prevent PDF generation for restricted users"""
        # Get the report record
        if isinstance(report_ref, str):
            report = self.env['ir.actions.report']._get_report_from_name(report_ref)
        else:
            report = report_ref

        # Check if this is a restricted report
        if report and report.report_name in RESTRICTED_REPORTS:
            if isinstance(docids, (list, tuple)):
                picking_ids = docids
            else:
                picking_ids = [docids]

            pickings = self.env['stock.picking'].browse(picking_ids)
            for picking in pickings:
                if not picking._is_user_allowed_to_print():
                    raise UserError(_("You are not allowed to print or download this picking report."))

        return super()._render_qweb_pdf(report_ref, docids, data=data)

    def _render_qweb_html(self, report_ref, docids, data=None):
        """Override to prevent HTML generation for restricted users"""
        # Get the report record
        if isinstance(report_ref, str):
            report = self.env['ir.actions.report']._get_report_from_name(report_ref)
        else:
            report = report_ref

        # Check if this is a restricted report
        if report and report.report_name in RESTRICTED_REPORTS:
            if isinstance(docids, (list, tuple)):
                picking_ids = docids
            else:
                picking_ids = [docids]

            pickings = self.env['stock.picking'].browse(picking_ids)
            for picking in pickings:
                if not picking._is_user_allowed_to_print():
                    raise UserError(_("You are not allowed to print or download this picking report."))

        return super()._render_qweb_html(report_ref, docids, data=data)

    def _get_report_from_name(self, report_name):
        """Get report record from name"""
        return self.search([('report_name', '=', report_name)], limit=1)

    def _render(self, template, values=None):
        """Override render method to catch report generation"""
        # Check if this is a restricted report
        if self.report_name in RESTRICTED_REPORTS:
            # Get docids from values if available
            if values and 'docs' in values:
                docs = values['docs']
                if hasattr(docs, 'ids'):
                    docids = docs.ids
                elif hasattr(docs, '_ids'):
                    docids = docs._ids
                else:
                    docids = [doc.id for doc in docs]

                pickings = self.env['stock.picking'].browse(docids)
                for picking in pickings:
                    if not picking._is_user_allowed_to_print():
                        raise UserError(_("You are not allowed to print or download this picking report."))

        return super()._render(template, values)



class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _is_user_allowed_to_print(self):
        """
        Define who can print QWeb reports for this picking.
        Modify this logic based on your rules.
        """
        self.ensure_one()
        company = self.company_id
        if company.can_print_picking_list:
            allowed_users = company.can_print_picking_list.ids

            return self.env.user.id in allowed_users
        return False

    def report_action(self, report_ref=None, config=True):
        """Intercept QWeb report rendering."""
        self.ensure_one()

        # Check if this is one of the reports we want to restrict
        if report_ref in RESTRICTED_REPORTS:
            if not self._is_user_allowed_to_print():
                raise ValidationError(_("You are not allowed to print this report."))

        # Proceed with normal report rendering
        return super().report_action(report_ref=report_ref, config=config)





    # a delivery  note to be linked to invoice
    def _get_share_url(self):
        """Generate a shareable URL for this sales order"""
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        url = f"{base_url}/web#id={self.id}&model=stock.picking&view_type=form"
        return url

    custom_return = fields.Boolean(string='Is Return Order', default=False)
    reason_for_return = fields.Char(string='Reason for Return', default=False)
    return_date = fields.Date(string='Return Date', default=False)
    invoice_id = fields.Many2one('account.move', string='Linked Invoice',
                                 copy=False)

    current_approver_id = fields.Many2one('res.users', string='Current Approver', readonly=True)
    level1_approved_by = fields.Many2one('res.users', string='Level 1 Approved By', readonly=True)
    level2_approved_by = fields.Many2one('res.users', string='Level 2 Approved By', readonly=True)
    level3_approved_by = fields.Many2one('res.users', string='Final Approved By', readonly=True)
    reject_reason = fields.Text("Rejection Reason", readonly=True)
    def action_request_approval(self):
        """Submit SO for approval"""
        for order in self:
            if order.state not in ['assigned']:
                raise UserError(_("Only draft orders can be submitted for approval."))

            company = order.company_id
            if not company.approved_level1_by or not company.approved_level2_by or not company.approved_level2_by:
                raise UserError(_("Please configure approvers in Company Settings."))

            order.write({
                'approval_status': 'pending_level_1',
                'current_approver_id': company.approved_level1_by[0].id
            })

            # Send Email to Level 1 Approver
            email_values = {
                'email_to': company.approved_level1_by[0].email,
                'email_from': self.env.company.email,
            }
            ctx = {
                'name': company.approved_level1_by[0].name,
                'ref': order.name,
                'url': order._get_share_url(),
                'user': self.env.user.name,
                'date': fields.Date.today(),
                'company_name': order.company_id.name,
            }
            template = self.env.ref('estates_customs.email_template_delivery_approval_all_levels_new')
            template.with_context(ctx).send_mail(order.id,
                                                           email_values=email_values,force_send=True)


    def _send_quotation_request_email_to_finance(self):
        """Notify finance team that a quotation is needed for a specific Sale Order."""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        company = self.company_id
        finance_team = company.posted_by  # You should define this M2M field in res.company

        for user in finance_team:
            if not user.partner_id.email:
                continue

            sale_order_url = f"{base_url}/web#id={self.sale_id.id}&model=sale.order&view_type=form"
            link = f'<a href="{sale_order_url}">View Sale Order</a>'

            email_values = {
                'subject': _('Quotation Needed for Sale Order: %s') % self.sale_id.name,
                'body_html': """
                    <p>Hello %s,</p>
                    <p>A quotation is required for the Sale Order <strong>%s</strong>.</p>
                    <p>
                        <strong>Customer:</strong> %s<br/>
                        <strong>Total:</strong> %s<br/>
                        <strong>Created by:</strong> %s<br/>
                        %s
                    </p>
                    <p>Please take necessary action.</p>
                    <p>Regards,<br/>Your Odoo System</p>
                """ % (
                    html.escape(user.name),
                    html.escape(self.sale_id.name),
                    html.escape(self.sale_id.partner_id.name or ''),
                    self.sale_id.amount_total,
                    html.escape(self.sale_id.create_uid.name),
                    link
                ),
                'email_to': user.partner_id.email,
                'auto_delete': True,
                'email_from': self.env.user.email or 'no-reply@yourcompany.com',
            }

            self.env['mail.mail'].create(email_values).send()

    def button_validate(self):
        """ Override to create invoice after delivery is validated """
        res = super().button_validate()
        company = self.company_id



        allowed_users = company.can_print_picking_list.ids
        # check if previously delivery note has been created with the invoice
        if self.sale_id and  not self.custom_return:
            self._send_quotation_request_email_to_finance()
            so_pending = self.env['stock.picking'].sudo().search([
                ('sale_id', '=', self.sale_id.id),
                ('invoice_id', '=', False),
                ('id', '!=', self.id),
                ('custom_return', '=', False),
                ('state', '=', 'done'),
                ('picking_type_id.code', '=', 'outgoing'),  # <-- Only outgoing shipments
            ])

            if so_pending:
                raise ValidationError(_(
                    "You cannot approve this order because there are completed outgoing shipments without invoices.\n"
                    "Please notify the finance department before proceeding!"
                ))
            if self.env.user.id not in allowed_users:
                raise UserError(_("Your Not authorised to approve this order"))
            # Proceed only if auto-invoicing is enabled
            # if self.env.context.get('create_invoice_on_delivery'):
            #     self._create_invoice_from_delivery()

            return res

    def _create_invoice_from_delivery(self):
        """ Call sales order's invoice creation method with this delivery """
        sale_order = self.sale_id
        if not sale_order:
            return

        # Trigger invoice creation on the related sales order
        wizard = self.env['sale.advance.payment.inv'].with_context(
            active_model='sale.order',
            active_ids=[sale_order.id],
            default_picking_ids=[(6, 0, [self.id])]  # pass current delivery note
        ).create({})

        invoice = wizard.create_invoices()
        return invoice




    @api.constrains('invoice_id')
    def _check_unique_invoice(self):
        for picking in self:
            if picking.invoice_id and self.search([
                ('invoice_id', '=', picking.invoice_id.id),
                ('id', '!=', picking.id)
            ]):
                raise ValidationError("This delivery note is already linked to another invoice.")
    # def action_open_invoice_wizard(self):
    #     self.ensure_one()
    #     return {
    #         'name': 'Create Invoice from Delivery',
    #         'type': 'ir.actions.act_window',
    #         'res_model': 'create.invoice.from.delivery',
    #         'view_mode': 'form',
    #         'target': 'new',
    #         'context': {
    #             'default_picking_ids': [(6, 0, [self.id])]
    #         }
    #     }

    supervisor_id = fields.Many2one('res.users', string='Supervisor',placeholder='Supervisor')
    driver_name = fields.Char(string='Driver Name',placeholder='Driver Name')
    driver_license = fields.Char(string='Driver License',placeholder='Driver License')
    driver_phone = fields.Char(string='Phone Number',placeholder='Phone Number')
    transporter_company = fields.Char(string='Transporter Company',placeholder='Transporter Company')
    truck_number = fields.Char(string='Truck Number',placeholder='Truck Number')
    trailer_number = fields.Char(string='Trailer Number',placeholder='Trailer Number')
    loading_pattern = fields.Html(string='Loading Pattern')
    remarks = fields.Text(string='Remarks')
    lpo_number = fields.Char(related='sale_id.lpo_number',
                             store=True,
                             string='LPO Number',tracking=True,
                             placeholder='LPO Number LPO/565..',
                             help='LPO Number from the customer')

    def print_loading_instruction(self):
        return self.env.ref('estates_customs.action_report_loading_instructions_id_card').report_action(self)