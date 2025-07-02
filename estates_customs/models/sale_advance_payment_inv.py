from odoo import models, fields, api
from odoo.exceptions import UserError


class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = 'sale.advance.payment.inv'

    picking_id = fields.Many2one(
        'stock.picking',
        string='Select Delivery Note',
        domain="[('sale_id', '=', sale_order_ids[0]), ('invoice_id', '=', False), ('state', '=', 'done')]"
    )
    lpo_number = fields.Char(string='LPO Number',
                             placeholder='LPO Number LPO/565..',
                             help='LPO Number from the customer')
    def create_invoices(self):
        """Override invoice creation to use selected delivery note if provided"""
        self.ensure_one()

        if self.advance_payment_method == 'delivered':
            # Use custom logic if delivery note is selected
            if self.picking_id:
                return self._create_invoice_from_delivery(self.sale_order_ids)
            else:
                return super().create_invoices()
        else:
            return super().create_invoices()

    def _create_invoice_from_delivery(self, sale_orders):
        """Create an invoice based on a specific delivery note"""
        sale_orders.ensure_one()
        order = sale_orders

        # Get delivered products from selected delivery note
        delivery_moves = self.env['stock.move'].search([
            ('picking_id', '=', self.picking_id.id),
            ('state', '=', 'done')
        ])

        # Map product IDs to delivered quantities
        delivered_qty_map = {}
        for move in delivery_moves:
            line = move.sale_line_id
            if not line or line.is_downpayment:
                continue
            delivered_qty_map.setdefault(line.id, 0)
            delivered_qty_map[line.id] += move.quantity

        # Prepare invoice lines with only delivered items
        invoice_line_vals = []
        for line in order.order_line:
            delivered_qty = delivered_qty_map.get(line.id, 0.0)
            if delivered_qty <= 0:
                continue

            invoice_line_vals.append((0, 0, {
                'product_id': line.product_id.id,
                'name': line.name,
                'quantity': delivered_qty,
                'price_unit': line.price_unit,
                'tax_ids': [(6, 0, line.tax_id.ids)],
                'sale_line_ids': [(4, line.id)]
            }))

        if not invoice_line_vals:
            raise UserError("No deliverable items found to invoice.")

        # Prepare invoice values
        invoice_vals = {
            'move_type': 'out_invoice',
            'lpo_number': self.sale_order_ids[0].lpo_number,
            'partner_id': order.partner_invoice_id.id,
            'invoice_origin': self.picking_id.name,
            'journal_id': self.env['account.journal'].search([('type', '=', 'sale'), ('company_id', '=', order.company_id.id)], limit=1).id,
            'invoice_line_ids': invoice_line_vals,
            'picking_id': self.picking_id.id,  # Link invoice to delivery
        }

        # Create invoice
        invoice = self.env['account.move'].create(invoice_vals)

        self.picking_id.write({'invoice_id': invoice.id})

        return invoice