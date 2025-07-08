from odoo import models, api, fields, _


class ProductPricelistItem(models.Model):
    _inherit = 'product.pricelist.item'

    purchase_price = fields.Float(
        string='Purchase Price',
        digits='Product Price',
        help="Price used for purchases if this pricelist is used in a supplier or warehouse"
    )

    def _compute_price(self, product, quantity, uom, date=False, **kwargs):
        if not self:
            # Return 0 if item is empty
            return 0.0

        self.ensure_one()

        if uom and uom != product.uom_id:
            quantity = uom._compute_quantity(quantity, product.uom_id)

        price = self.purchase_price or self.fixed_price
        if not price:
            return super()._compute_price(product, quantity, uom, date=date, **kwargs)

        if uom and uom != product.uom_id:
            price = product.uom_id._compute_price(price, uom)

        return price



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

        # ✅ return after all lines processed
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Success',
                'message': 'All line prices updated from warehouse pricelist.',
                'sticky': False,
            }
        }
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

    @api.model
    def _get_product_price(self, product, qty, uom=None, date=False, **kwargs):
        """
        Get product price considering purchase_price and warehouse
        """
        if not uom:
            uom = product.uom_id

        # Base price from parent method (used as fallback)
        price = super()._get_product_price(product, qty, uom=product.uom_id, date=date, **kwargs)
        items = self._get_pricelist_items(product, qty, uom, date)
        item = items[0] if items else None
        if item:
            try:
                price = item._compute_price(product, qty, uom, date)
            except Exception:
                price = product.standard_price

        # ✅ Fixed conversion back to requested uom
        return product.uom_id._compute_price(price, uom)

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.onchange('product_id', 'product_qty', 'product_uom')
    def onchange_product_id_get_price_by_warehouse(self):
        if not self.product_id:
            return

        warehouse = self.order_id.picking_type_id.warehouse_id
        if warehouse:
            pricelist_id = self.env['product.pricelist'].sudo().search([('warehouse_id','=',warehouse.id)],limit=1)
            if pricelist_id:
                self.price_unit = pricelist_id._get_product_price(
                    self.product_id,
                    self.product_qty,
                    uom=self.product_uom,
                    warehouse=warehouse  # <-- Important!
                )
            else:
                self.price_unit = self.product_id.standard_price
        else:
            self.price_unit = self.product_id.standard_price

