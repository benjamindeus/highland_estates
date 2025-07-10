from odoo import models, api, fields, _
from odoo.exceptions import UserError
class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    purchase_price = fields.Float(
        string='Purchase Price',
        digits='Product Price',
        help="Price used for purchases if this pricelist is used in a supplier or warehouse"
    )


    def _compute_price(self, product, quantity, uom, date=False, **kwargs):
        if not self:
            return 0.0

        price = False
        self.ensure_one()
        if kwargs.get('active_model'):
            if self.purchase_price:
                return self.purchase_price
            else:
                return price


        return super()._compute_price(product, quantity, uom, date, **kwargs)





class ProductPricelist(models.Model):
    _inherit = 'product.pricelist'
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',

    )
    def _get_pricelist_items(self, product, qty=False, uom=False, date=False):
        """Helper to get relevant pricelist items for a product"""
        self.ensure_one()
        domain = [('pricelist_id', '=', self.id)]

        # Specific variant
        variant_items = self.env['product.pricelist.item'].search(domain + [
            ('applied_on', '=', '0_product_variant'),
            ('product_id', '=', product.id),
        ])

        # General product template
        template_items = self.env['product.pricelist.item'].search(domain + [
            ('applied_on', '=', '1_product'),
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
        ])

        return variant_items | template_items

    # @api.model
    def _get_product_price(self, product, qty, uom=None, date=False, **kwargs):
        """
        Get product price considering purchase_price and warehouse
        """
        if not uom:
            uom = product.uom_id

        # Base price from parent method (used as fallback)
        price = super()._get_product_price(product, qty, uom=product.uom_id, date=date, **kwargs)
        active_model = kwargs.get('active_model',None)
        items = self._get_pricelist_items(product, qty, uom, date)
        item = items[0] if items else None


        if item:
            try:
                price = item._compute_price(product, qty, uom, date,active_model=active_model)
            except Exception:
                price = product.standard_price

        # ✅ Fixed conversion back to requested uom
        return product.uom_id._compute_price(price, uom)

