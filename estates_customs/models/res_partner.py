from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
from datetime import datetime


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_efd_vrn_registered = fields.Boolean(
        string="Is VRN Registered",
        default=False,
        help="Whether the partner is registered with EFD/VRN."
    )
    efd_vrn_number = fields.Char(string="EFD VRN Number")
    def _get_share_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return f"{base_url}/web#id={self.id}&model=res.partner&view_type=form&menu_id="
