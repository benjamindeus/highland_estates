from odoo import api, fields, models

class ResCompany(models.Model):
    _inherit = 'res.company'
    vfd_url = fields.Char(string="VFD URL",placeholder= 'https://test.myvfd.app/api/v1/receipt/post',default='https://test.myvfd.app/api/v1/receipt/post',required=True)
    x_tin_vfd = fields.Char(string="X-TIN VFD",placeholder= '1234567890123',default='152899165',required=True)
    vfd_authorization_header = fields.Char(string="VFD Authorization Header",required=True,default='Bearer 6b2927d40ed8eba9d030f5308efee7ee7a34e760')

    # Company Approvals
    approved_level1_by = fields.Many2many('res.users', 'res_company_approved_level1_by_rel',
                                   'company_id', 'a_user_id', string='Approver 1')

    approved_level2_by = fields.Many2many('res.users', 'res_company_approved_level2_by_rel',
                                   'company_id', 'a_user_id', string='Approver 2')
    last_approver = fields.Many2many('res.users', 'res_company_approved_last_by_rel',
                                   'company_id', 'a_user_id', string='Last Approver')
    posted_by = fields.Many2many('res.users', 'res_company_posted_by_rel',
                                   'company_id', 'a_user_id', string='To Post')