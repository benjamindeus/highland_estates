from odoo import models, api, fields, _
from odoo.exceptions import UserError
import html

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def action_recompute_prices_from_warehouse(self):
        """
        Recompute all line prices based on current warehouse's pricelist.
        """
        for order in self:
            warehouse = order.picking_type_id.warehouse_id
            pricelist_id = self.env['product.pricelist'].sudo().search([('warehouse_id', '=', warehouse.id)], limit=1)
            pricelist = pricelist_id

            for line in order.order_line:
                if not line.product_id:
                    continue

                if pricelist:
                    price = pricelist._get_product_price(
                        line.product_id,
                        line.product_qty,
                        uom=line.product_uom,
                        warehouse=warehouse
                    )
                else:
                    price = line.product_id.standard_price

                line.price_unit = price

    @api.model
    def _get_price_from_warehouse_pricelist(self, product, qty, uom, warehouse_id):
        """Get purchase price for product from warehouse-specific pricelist"""
        if not warehouse_id:
            return product.standard_price

        warehouse = self.env['stock.warehouse'].browse(warehouse_id)
        pricelist = warehouse.pricelist_id
        if not pricelist:
            return product.standard_price

        return pricelist._get_product_price(
            product, qty, uom=uom, warehouse=warehouse
        )

    def _send_new_po_notification_email(self):
        """Send email notification to selected users when a new PO is created."""
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        company = self.company_id
        users = company.to_be_notified
        for user in users:
            if not user.partner_id.email:
                continue

            po_url = f"{base_url}/web#id={self.id}&model=purchase.order&view_type=form"
            po_link = f'<a href="{po_url}">Open Purchase Order</a>'

            email_values = {
                'subject': _('New Purchase Order Created: %s') % self.name,
                'body_html': """
                    <p>Hello %s,</p>
                    <p>A new Purchase Order <strong>%s</strong> has been created.</p>
                    <p>
                        <strong>Vendor:</strong> %s<br/>
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
                    po_link
                ),
                'email_to': user.partner_id.email,
                'auto_delete': True,
                'email_from': self.env.user.email or 'no-reply@yourcompany.com',
            }

            self.env['mail.mail'].create(email_values).send()

    @api.model
    def create(self, vals):
        user = self.env.user
        allowed_users = user.company_id.can_create_purchases

        if user not in allowed_users:
            allowed_user_names = ', '.join(allowed_users.mapped('name')) or 'No users allowed'
            raise UserError(_(
                "You are not allowed to create Purchase Orders.\n\n"
                "Only the following users can create purchases:\n%s"
            ) % allowed_user_names)
        record = super().create(vals)
        # Send email after record is successfully created
        record._send_new_po_notification_email()
        return record

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'


    @api.depends('product_uom', 'product_qty', 'product_id.uom_id')
    def _compute_product_uom_qty(self):
        for line in self:
            # Compute the product_uom_qty
            if line.product_id and line.product_id.uom_id != line.product_uom:
                line.product_uom_qty = line.product_uom._compute_quantity(line.product_qty, line.product_id.uom_id)
            else:
                line.product_uom_qty = line.product_qty

            # Set price from warehouse pricelist
            warehouse = line.order_id.picking_type_id.warehouse_id
            if line.product_id and warehouse:
                pricelist = line.env['product.pricelist'].sudo().search([('warehouse_id', '=', warehouse.id)], limit=1)
                if pricelist:
                    price = pricelist._get_product_price(
                        line.product_id,
                        line.product_qty,
                        uom=line.product_uom,
                        warehouse=warehouse,
                        active_model='purchase.order',
                    )
                    line.price_unit = price
                else:
                    line.price_unit = line.product_id.standard_price
            elif line.product_id:
                line.price_unit = line.product_id.standard_price

    @api.onchange('product_id', 'product_qty', 'product_uom', 'order_id.picking_type_id')
    def onchange_product_id_warehouse_notify_missing_price(self):
        if not self.product_id:
            return

        warehouse = self.order_id.picking_type_id.warehouse_id
        if warehouse:
            pricelist = self.env['product.pricelist'].sudo().search([('warehouse_id', '=', warehouse.id)], limit=1)
            if pricelist:
                items = pricelist._get_pricelist_items(self.product_id)
                if not items:
                    return {
                        'warning': {
                            'title': _('Missing Price'),
                            'message': _('This product is not listed in the pricelist assigned to the warehouse: %s') % warehouse.display_name
                        }
                    }
            else:
                return {
                    'warning': {
                        'title': _('No Pricelist Found'),
                        'message': _('No pricelist is assigned to the selected warehouse.')
                    }
                }

