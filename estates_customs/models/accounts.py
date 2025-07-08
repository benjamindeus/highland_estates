from odoo import fields, models
from PIL import ImageFont
from odoo.exceptions import RedirectWarning, UserError, ValidationError
from odoo import models, fields, api, _, osv
import requests
from datetime import datetime
import qrcode
from io import BytesIO
import base64
import json
from urllib.request import urlopen
class AccountMove(models.Model):
    _inherit = 'account.move'
    def unlink(self):
        for move in self:
            if move.vfd_receipt_no or move.tra_qrcode_url:
                raise UserError(_(
                    "You cannot delete this record because it has a VFD Receipt Number and a TRA QR Code assigned."
                ))
        return super(AccountMove, self).unlink()
    # new fields
    picking_id = fields.Many2one('stock.picking', string='Delivery Note',tracking=True,
                                 domain=[('state', '=', 'done')], copy=False)
    lpo_number = fields.Char(string='LPO Number',tracking=True,
                             placeholder='LPO Number LPO/565..',
                             help='LPO Number from the customer')

    is_vfd_issues = fields.Boolean(string='Is VFD Issues',default=False,copy=False)
    vfd_qrcode_url = fields.Char(string='VFD QR Code URL',copy=False)
    tra_qrcode_url = fields.Char(string='TRA QR Code URL',copy=False)
    vfd_receipt_no = fields.Char(string='VFD Receipt No',copy=False)
    vfd_qr_code = fields.Binary(string="VFD QR Code", copy=False)
    vfd_log_message = fields.Text(string="VFD Response Message", copy=False)

    def get_vfd_qr_data(self,qrserver_url):
        if '?data=' in qrserver_url:
            return qrserver_url.split('?data=')[1]
        return ''
    def generate_efd_tra_receipt_please(self):
        for rec in self:
            if self.vfd_receipt_no:
                raise UserError(_("Receipt %s already generated.") % self.vfd_receipt_no)
            if not rec.partner_id.vat or not rec.partner_id.vat.isdigit():
                raise UserError(_("Partner %s must have a valid TIN number eg 123456.") % rec.partner_id.name)
            if rec.partner_id.is_efd_vrn_registered and ( not rec.partner_id.efd_vrn_number or not rec.partner_id.vat.isdigit()):
                raise UserError(_("Partner %s must have a valid VAT number eg 123456.") % rec.partner_id.name)


            receipt_datetime = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            company = rec.company_id
            data = {
            # "invoice_reference": self.name,
            # "date": rec.invoice_date.isoformat() if rec.invoice_date else datetime.now().date().isoformat(),
            # "total_amount": float(self.amount_total),
            "receipt_date": receipt_datetime,
            "customer_id": str(rec.partner_id.vat),
            "customer_idtype": "1",
            "customer_email": rec.partner_id.email or "unknown@example.com",
            "customer_address": rec.partner_id.contact_address or "Unknown",
            "customer_name": rec.partner_id.name or "Customer",
            "customer_vrn": str(rec.partner_id.vat) if rec.partner_id.is_efd_vrn_registered else "",
            "trader_docno": self.name,
            "taxexcl": 1,
            "items": [
                {
                    "itemcode": line.name or 'line',
                    "itemdesc": line.name or 'line',
                    "quantity": float(line.quantity),
                    "amount": float(line.price_unit),
                    "discount": float(line.discount),
                    "taxcode": "5",
                    # "taxes": [tax.amount for tax in line.tax_ids],
                } for line in self.invoice_line_ids
            ],
            "payments": {
                "paytype": "cash",
                "payamount": float(rec.amount_total)
            },

        }
            headers = {
                'X-Tin': str(company.x_tin_vfd),
                'Accept':'application/json',
                'Content-Type':'application/json',
                'Authorization': str(company.vfd_authorization_header)}
            # try:
            response = requests.post(
                str(company.vfd_url),
                json=data,
                headers=headers
            )
            response.raise_for_status()
            result = response.json()
            print(">>>>>>>>>RESULTS<<<<<<<<<<<<<<<<<<<<")
            print(result)
            print(">>>>>>>>>RESULTS<<<<<<<<<<<<<<<<<<<<")
            if 'message' in result and 'receipt_id' in result:
                qr_img_base64 = False
                if result.get('qrcode_url'):
                    url = result['qrcode_url']
                    tra_url = self.get_vfd_qr_data(url)
                    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H)
                    # qr.add_data(result['qrcode_url'])
                    qr.add_data(tra_url)
                    qr.make(fit=True)
                    img = qr.make_image(fill_color="black", back_color="white")
                    buffer = BytesIO()
                    img.save(buffer, format="PNG")
                    qr_img_base64 = base64.b64encode(buffer.getvalue())
                rec.write({
                    'vfd_receipt_no': result.get('receipt_no'),
                    'vfd_qrcode_url': result.get('qrcode_url'),
                    'tra_qrcode_url':str(tra_url),
                    'vfd_qr_code': qr_img_base64,
                    'is_vfd_issues': True,
                    'vfd_log_message':result
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('VFD CREATED SUCCESSFULLY!'),
                        'message': _(f'Receippt generated sucessfully Receipt No: {result.get('receipt_no')}'),
                        'type': 'success',
                        'sticky': True,
                    }
                }

            elif 'error' in result:
                rec.write({
                    'vfd_log_message': result
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('VFD GENERATION ERROR'),
                        'message': _(f'Un expected Error occured: {result.get('error')}'),
                        'type': 'success',
                        'sticky': True,
                    }
                }

            else:
                raise UserError("Unexpected response from VFD API.")

            qr_img_base64 = False
            if qrcode_url:
                qr_img_response = requests.get(qrcode_url)
                if qr_img_response.status_code == 200:
                    qr_img_base64 = base64.b64encode(qr_img_response.content)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('VFD GENERATION STATUS'),
                    'message': _("VFD Receipt Generated:\n\nReceipt No: %s" % vfd_receipt_no),
                    'type': 'success',
                    'sticky': True,
                }
            }

            #
            # except requests.exceptions.RequestException as e:
            #     raise UserError(_(f"TRA VFD Request Failed:\n{e}"))