# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class StockReconciliationLine(models.Model):
    _name = 'stock.reconciliation.line'
    _description = 'Stock Reconciliation Line'

    product_id = fields.Many2one('product.product', string='Product', required=True)
    product_name = fields.Char(string='Product Name')
    barcode = fields.Char(string='Barcode')
    categ_id = fields.Many2one('product.category', string='Product Category')
    initial_qty = fields.Float(string='Initial Qty', digits='Product Unit of Measure')
    ending_qty = fields.Float(string='Ending Qty', digits='Product Unit of Measure')
    sold_qty = fields.Float(string='Sold Qty', digits='Product Unit of Measure')
    quantity_in = fields.Float(string='Quantity In', digits='Product Unit of Measure')
    total_cost = fields.Float(string='Total Cost')
    total_sales = fields.Float(string='Total Sales')
    total_cost_incoming = fields.Float(string='Total Cost Of Incoming Goods')
    total_sales_incoming = fields.Float(string='Total Sales Of Incoming Goods')
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)

    def action_open_wizard(self):
        return {
            'name': _('Stock Reconciliation'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.reconciliation.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
