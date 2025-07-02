from odoo import models, fields, api
from odoo.exceptions import UserError

class CreateInvoiceFromDelivery(models.TransientModel):
    _name = 'create.invoice.from.delivery'
    _description = 'Create Invoice from Delivery'

    picking_ids = fields.Many2many(
        'stock.picking',
        string='Deliveries',
        required=True,
        domain=[('state', '=', 'done'), ('invoice_id', '=', False)]
    )

    def action_create_invoice_from_delivery(self):
        self.ensure_one()
        if not self.sale_id:
            raise UserError("This delivery is not linked to a sales order.")

        sale_order = self.sale_id

        # Prepare invoice lines based on delivery moves
        invoice_lines = []
        for move in self.move_ids_without_package:
            line_vals = {
                'product_id': move.product_id.id,
                'quantity': move.quantity,
                'price_unit': move.sale_line_id.price_unit,
                'tax_ids': [(6, 0, move.sale_line_id.tax_id.ids)],
            }
            invoice_lines.append((0, 0, line_vals))

        # Prepare invoice values
        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': sale_order.partner_invoice_id.id,
            'invoice_origin': self.name,
            'invoice_line_ids': invoice_lines,
            'journal_id': self.env['account.journal'].search([('type', '=', 'sale')], limit=1).id,
        }

        # Create invoice
        invoice = self.env['account.move'].create(invoice_vals)

        # Link delivery note to invoice
        invoice.picking_id = self.id
        self.invoice_id = invoice.id

        # Open invoice form
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': invoice.id,
            'view_mode': 'form',
            'target': 'current',
        }