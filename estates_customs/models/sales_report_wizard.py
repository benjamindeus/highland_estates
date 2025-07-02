from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime
import base64
from io import BytesIO
import xlsxwriter
from datetime import date, timedelta
from calendar import monthrange


class SaleReportWizard(models.TransientModel):
    _name = 'sale.report.wizard'
    _description = 'Sales & Customer Statement Report'

    def _default_date_from(self):
        today = date.today()
        return today.replace(day=1)

    def _default_date_to(self):
        today = date.today()
        last_day = monthrange(today.year, today.month)[1]
        return today.replace(day=last_day)

    date_from = fields.Date(
        string="Start Date",
        required=True,
        placeholder='start date',
        default=lambda self: self._default_date_from()
    )

    date_to = fields.Date(
        string="End Date",
        required=True,
        placeholder='end date',
        default=lambda self: self._default_date_to()
    )
    user_id = fields.Many2one('res.users', string='Salesperson',placeholder='Salesperson')
    partner_id = fields.Many2one('res.partner', string='Customer',placeholder='Customer')
    report_format = fields.Selection(
        [('excel', 'Excel')],
        string="Report Format",
        default='excel',
        required=True
    )
    report_type = fields.Selection(
        [
            ('product_sales', 'Sales by Product'),
            ('customer_summary', 'Sales Summary by Customer'),
            ('salesperson_performance', 'Salesperson Performance'),
            ('invoice_lines_summary', 'Invoice Lines Summary'),
            ('customer_statement', 'Customer Statement')
        ],
        string="Report Type",
        required=True,
        placeholder='Report Type'
    )

    def action_generate_report(self):
        self.ensure_one()

        if self.report_type in ['product_sales', 'customer_summary', 'salesperson_performance']:
            domain = self._build_domain()
            order_lines = self.env['sale.order.line'].search(domain)
            if not order_lines:
                raise UserError("No sales found matching the criteria.")

        elif self.report_type == 'invoice_lines_summary':
            invoice_lines = self._get_invoice_lines()
            if not invoice_lines:
                raise UserError("No invoice lines found matching the criteria.")

        elif self.report_type == 'customer_statement':
            return self._generate_customer_statement_excel()

        if self.report_format == 'excel':
            if self.report_type in ['product_sales', 'customer_summary', 'salesperson_performance']:
                return self._generate_excel_report(order_lines)
            elif self.report_type == 'invoice_lines_summary':
                return self._generate_invoice_lines_excel(invoice_lines)

    def _build_domain(self):
        """Build domain for sale.order.line"""
        domain = [
            ('order_id.date_order', '>=', self.date_from),
            ('order_id.date_order', '<=', self.date_to),
            ('order_id.state', 'in', ['sale', 'done'])
        ]
        if self.user_id:
            domain.append(('order_id.user_id', '=', self.user_id.id))
        if self.partner_id:
            domain.append(('order_id.partner_id', '=', self.partner_id.id))
        return domain

    def _get_invoice_lines(self):
        """Get invoice lines based on SOs in given date range"""
        sale_orders = self.env['sale.order'].search([
            ('date_order', '>=', self.date_from),
            ('date_order', '<=', self.date_to),
            ('state', 'in', ['sale', 'done']),
        ])
        if self.partner_id:
            sale_orders = sale_orders.filtered(lambda so: so.partner_id == self.partner_id)

        invoice_lines = self.env['account.move.line'].search([
            ('move_id.move_type', '=', 'out_invoice'),
            ('move_id.invoice_date', '>=', self.date_from),
            ('move_id.invoice_date', '<=', self.date_to),
            ('move_id.state', '=', 'posted'),
            ('sale_line_ids.order_id', 'in', sale_orders.ids)
        ])

        return invoice_lines

    def _generate_excel_report(self, order_lines):
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet("SALES REPORT")

        header_style = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
        amount_style = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        normal_style = workbook.add_format({'border': 1})

        headers = ["SNO", "Order Date", "Product", "Customer", "SO No", "Tons", "Bags", "Rate per Bag", "Amount", "LPO No"]

        worksheet.write_row(0, 0, headers, header_style)

        row = 1
        sno = 1
        total_bags = 0
        total_tons = 0
        total_amount = 0

        for line in order_lines:
            weight_per_bag_kg = line.product_id.weight / 1000
            total_kg = line.product_uom_qty * weight_per_bag_kg

            worksheet.write(row, 0, sno, normal_style)
            worksheet.write(row, 1, str(line.order_id.date_order) or "", normal_style)
            worksheet.write(row, 2, line.product_id.name or "", normal_style)
            worksheet.write(row, 3, line.order_id.partner_id.name or "", normal_style)
            worksheet.write(row, 4, line.order_id.name or "", normal_style)
            worksheet.write(row, 5, total_kg, normal_style)
            worksheet.write(row, 6, line.product_uom_qty, normal_style)
            worksheet.write(row, 7, line.price_unit, amount_style)
            worksheet.write(row, 8, line.price_subtotal, amount_style)
            worksheet.write(row, 9, line.order_id.lpo_number or "", normal_style)

            row += 1
            sno += 1
            total_bags += line.product_uom_qty
            total_tons += total_kg
            total_amount += line.price_subtotal

        # Total Row
        worksheet.write(row, 0, "Total", header_style)
        worksheet.write(row, 1, "", normal_style)
        worksheet.write(row, 2, "", normal_style)
        worksheet.write(row, 3, "", normal_style)
        worksheet.write(row, 4, "", normal_style)
        worksheet.write(row, 5, total_tons, amount_style)
        worksheet.write(row, 6, total_bags, amount_style)
        worksheet.write(row, 7, "", normal_style)
        worksheet.write(row, 8, total_amount, amount_style)
        worksheet.write(row, 9, "", normal_style)

        worksheet.autofilter('A1:J1')
        worksheet.set_column('A:A', 5)
        worksheet.set_column('B:B', 15)
        worksheet.set_column('C:C', 25)
        worksheet.set_column('D:D', 20)
        worksheet.set_column('E:E', 15)
        worksheet.set_column('F:F', 12)
        worksheet.set_column('G:G', 12)
        worksheet.set_column('H:H', 12)
        worksheet.set_column('I:I', 12)
        worksheet.set_column('J:J', 15)

        workbook.close()
        output.seek(0)

        filename = f"Sales_Report_{self.date_from}_{self.date_to}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': 'sale.report.wizard',
            'res_id': self.id,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}/{filename}?download=true',
            'target': 'self',
        }

    def _generate_invoice_lines_excel(self, invoice_lines):
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet("Invoice Lines")

        header_style = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
        amount_style = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        normal_style = workbook.add_format({'border': 1})

        headers = ["Date", "Customer", "Product", "Invoice", "Qty", "Rate", "Total", "LPO No"]
        worksheet.write_row(0, 0, headers, header_style)

        row = 1
        total_qty = 0
        total_amount = 0

        for inv_line in invoice_lines:
            worksheet.write(row, 0, str(inv_line.move_id.invoice_date), normal_style)
            worksheet.write(row, 1, inv_line.move_id.partner_id.name or "", normal_style)
            worksheet.write(row, 2, inv_line.product_id.name or "", normal_style)
            worksheet.write(row, 3, inv_line.move_id.name or "", normal_style)
            worksheet.write(row, 4, inv_line.quantity, normal_style)
            worksheet.write(row, 5, inv_line.price_unit, amount_style)
            worksheet.write(row, 6, inv_line.price_subtotal, amount_style)
            worksheet.write(row, 7, inv_line.move_id.invoice_origin or "", normal_style)

            row += 1
            total_qty += inv_line.quantity
            total_amount += inv_line.price_subtotal

        # Total Row
        worksheet.write(row, 0, "Total", header_style)
        worksheet.write(row, 1, "", normal_style)
        worksheet.write(row, 2, "", normal_style)
        worksheet.write(row, 3, "", normal_style)
        worksheet.write(row, 4, total_qty, normal_style)
        worksheet.write(row, 5, "", normal_style)
        worksheet.write(row, 6, total_amount, amount_style)
        worksheet.write(row, 7, "", normal_style)

        worksheet.autofilter('A1:H1')
        worksheet.set_column('A:A', 15)
        worksheet.set_column('B:B', 25)
        worksheet.set_column('C:C', 25)
        worksheet.set_column('D:D', 15)
        worksheet.set_column('E:E', 12)
        worksheet.set_column('F:F', 12)
        worksheet.set_column('G:G', 12)
        worksheet.set_column('H:H', 15)

        workbook.close()
        output.seek(0)

        filename = f"Invoice_Lines_Summary_{self.date_from}_{self.date_to}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': 'sale.report.wizard',
            'res_id': self.id,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}/{filename}?download=true',
            'target': 'self',
        }

    def _generate_customer_statement_excel(self):
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet("Customer Statement")

        header_style = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
        amount_style = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        normal_style = workbook.add_format({'border': 1})

        worksheet.write_row(0, 0, ["Customer", "Date", "Document", "Description", "Debit", "Credit", "Balance"], header_style)

        partners = self.partner_id or self.env['res.partner'].search([])
        row = 1

        for partner in partners:
            opening_balance = self._get_opening_balance(partner)
            closing_balance = opening_balance

            worksheet.write(row, 0, partner.name, normal_style)
            worksheet.write(row, 1, str(self.date_from), normal_style)
            worksheet.write(row, 2, "Opening Balance", normal_style)
            worksheet.write(row, 3, "Balance Carried Forward", normal_style)
            worksheet.write(row, 4, "", normal_style)
            worksheet.write(row, 5, "", normal_style)
            worksheet.write(row, 6, opening_balance, amount_style)
            row += 1

            invoices = self.env['account.move'].search([
                ('partner_id', '=', partner.id),
                ('move_type', '=', 'out_invoice'),
                ('invoice_date', '>=', self.date_from),
                ('invoice_date', '<=', self.date_to),
                ('state', '=', 'posted')
            ])
            for inv in invoices:
                closing_balance += inv.amount_total
                worksheet.write(row, 0, partner.name, normal_style)
                worksheet.write(row, 1, str(inv.invoice_date), normal_style)
                worksheet.write(row, 2, inv.name, normal_style)
                worksheet.write(row, 3, f"Invoice {inv.name}", normal_style)
                worksheet.write(row, 4, inv.amount_total, amount_style)
                worksheet.write(row, 5, "", normal_style)
                worksheet.write(row, 6, closing_balance, amount_style)
                row += 1

            payments = self.env['account.payment'].search([
                ('partner_id', '=', partner.id),
                ('date', '>=', self.date_from),
                ('date', '<=', self.date_to),
                ('state', '=', 'posted'),
                ('payment_type', '=', 'inbound')
            ])
            for payment in payments:
                closing_balance -= payment.amount
                worksheet.write(row, 0, partner.name, normal_style)
                worksheet.write(row, 1, str(payment.payment_date), normal_style)
                worksheet.write(row, 2, payment.name, normal_style)
                worksheet.write(row, 3, f"Payment {payment.name}", normal_style)
                worksheet.write(row, 4, "", normal_style)
                worksheet.write(row, 5, payment.amount, amount_style)
                worksheet.write(row, 6, closing_balance, amount_style)
                row += 1

            worksheet.write(row, 0, partner.name, normal_style)
            worksheet.write(row, 1, "", normal_style)
            worksheet.write(row, 2, "", normal_style)
            worksheet.write(row, 3, "Closing Balance", normal_style)
            worksheet.write(row, 4, "", normal_style)
            worksheet.write(row, 5, "", normal_style)
            worksheet.write(row, 6, closing_balance, amount_style)
            row += 2

        worksheet.autofilter('A1:G1')
        worksheet.set_column('A:A', 20)
        worksheet.set_column('B:B', 15)
        worksheet.set_column('C:C', 15)
        worksheet.set_column('D:D', 30)
        worksheet.set_column('E:E', 15)
        worksheet.set_column('F:F', 15)
        worksheet.set_column('G:G', 15)

        workbook.close()
        output.seek(0)

        filename = f"Customer_Statement_{self.date_from}_{self.date_to}.xlsx"
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': 'sale.report.wizard',
            'res_id': self.id,
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}/{filename}?download=true',
            'target': 'self',
        }

    def _get_opening_balance(self, partner):
        move_lines = self.env['account.move.line'].search([
            ('partner_id', '=', partner.id),
            ('date', '<', self.date_from),
            ('account_id.account_type', '=', 'asset_receivable'),
            ('parent_state', '=', 'posted')
        ])
        return sum(move_lines.mapped('balance'))

    def _generate_pdf_report(self, order_lines):
        # Optional: Add QWeb template logic here later
        return True