from odoo import models, fields, api, _, osv
from odoo.exceptions import RedirectWarning, UserError, ValidationError


class SaleOrder(models.Model):
    _inherit = 'sale.order'
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
        placeholder='LPO/565..',
        help='LPO Number from the customer'
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

            # Send Email to Level 1 Approver
            email_values = {
                'email_to': company.approved_level1_by[0].email,
                'email_from': self.env.company.email,
            }
            custom_values = {
                'url': self._get_share_url(),
                'company_name': self.env.company.name,
                'name':  company.approved_level1_by[0].name,
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

        # Send Email to Level 2 Approver
        # Send Email to Level 1 Approver
        email_values = {
            'email_to': company.approved_level2_by[0].email,
            'email_from': self.env.company.email,
        }
        custom_values = {
            'url': self._get_share_url(),
            'company_name': self.env.company.name,
            'name': company.approved_level2_by[0].name,
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

        # Send Email to Level 3 Approver
        email_values = {
            'email_to': company.last_approver[0].email,
            'email_from': self.env.company.email,
        }
        custom_values = {
            'url': self._get_share_url(),
            'company_name': self.env.company.name,
            'name': company.last_approver[0].name,
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
        email_values = {
            'email_to': company.posted_by[0].email,
            'email_from': self.env.company.email,
        }
        custom_values = {
            'url': self._get_share_url(),
            'company_name': self.env.company.name,
            'name': company.posted_by[0].name,
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










class StockPicking(models.Model):
    _inherit = 'stock.picking'
    # a delivery  note to be linked to invoice
    def _get_share_url(self):
        """Generate a shareable URL for this sales order"""
        self.ensure_one()
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        url = f"{base_url}/web#id={self.id}&model=stock.picking&view_type=form"
        return url


    invoice_id = fields.Many2one('account.move', string='Linked Invoice',
                                 copy=False)

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

        # Send Email to Level 2 Approver
        # Send Email to Level 1 Approver
        email_values = {
            'email_to': company.approved_level2_by[0].email,
            'email_from': self.env.company.email,
        }
        custom_values = {
            'url': self._get_share_url(),
            'company_name': self.env.company.name,
            'name': company.approved_level2_by[0].name,
            'user': self.env.user.name,
            'date': fields.Date.today(),
        }
        template = self.env.ref('estates_customs.email_template_delivery_approval_all_levels_new')
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

        # Send Email to Level 3 Approver
        email_values = {
            'email_to': company.last_approver[0].email,
            'email_from': self.env.company.email,
        }
        custom_values = {
            'url': self._get_share_url(),
            'company_name': self.env.company.name,
            'name': company.last_approver[0].name,
            'user': self.env.user.name,
            'date': fields.Date.today(),
        }
        template = self.env.ref('estates_customs.email_template_delivery_approval_all_levels_new')
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
        email_values = {
            'email_to': company.posted_by[0].email,
            'email_from': self.env.company.email,
        }
        custom_values = {
            'url': self._get_share_url(),
            'company_name': self.env.company.name,
            'name': company.posted_by[0].name,
            'user': self.env.user.name,
            'date': fields.Date.today(),
        }
        template = self.env.ref('estates_customs.email_template_delivery_approval_all_levels_new')
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
        template = self.env.ref('custom_approval_flow.email_template_delivery_approval_all_levels_new')
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
    def button_validate(self):
        """ Override to create invoice after delivery is validated """
        res = super().button_validate()
        if self.approval_status not in ['approved']:
            raise UserError(_("This order must be fully approved before confirming."))
        # Proceed only if auto-invoicing is enabled
        if self.env.context.get('create_invoice_on_delivery'):
            self._create_invoice_from_delivery()

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
    def action_open_invoice_wizard(self):
        self.ensure_one()
        return {
            'name': 'Create Invoice from Delivery',
            'type': 'ir.actions.act_window',
            'res_model': 'create.invoice.from.delivery',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_picking_ids': [(6, 0, [self.id])]
            }
        }

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