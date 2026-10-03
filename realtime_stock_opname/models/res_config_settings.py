# -*- coding: utf-8 -*-
from odoo import fields, models, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    stock_opname_user_ids = fields.Many2many(
        'res.users',
        'rel_stock_opname_config_users',
        'config_id',
        'user_id',
        string='Allowed Users',
        help='Specific users who are allowed to access the Realtime Stock Opname menu in the backend.'
    )
    stock_opname_apply_user_ids = fields.Many2many(
        'res.users',
        'rel_stock_opname_config_apply_users',
        'config_id',
        'user_id',
        string='Allowed Apply Adjustment Users',
        help='Specific users who are allowed to use the Apply Adjustment button on stock opname sessions.'
    )
    stock_opname_lock_user_ids = fields.Many2many(
        'res.users',
        'rel_stock_opname_config_lock_users',
        'config_id',
        'user_id',
        string='Allowed Document Lock Users',
        help='Specific users who are allowed to use the Document Lock button on stock opname sessions.'
    )
    stock_opname_unlock_user_ids = fields.Many2many(
        'res.users',
        'rel_stock_opname_config_unlock_users',
        'config_id',
        'user_id',
        string='Allowed Unlock Users',
        help='Specific users who are allowed to use the Unlock button on completed stock opname sessions.'
    )
    stock_opname_delete_user_ids = fields.Many2many(
        'res.users',
        'rel_stock_opname_config_delete_users',
        'config_id',
        'user_id',
        string='Allowed Delete Line Users',
        help='Specific users who are allowed to delete lines in Realtime Stock Opname.'
    )
    stock_inventory_audit_user_ids = fields.Many2many(
        'res.users',
        'rel_stock_inventory_audit_config_users',
        'config_id',
        'user_id',
        string='Allowed Users',
        help='Specific users who are allowed to access the Stock Inventory Audit Opname menu in the backend.'
    )
    stock_opname_location_ids = fields.Many2many(
        'stock.location',
        'rel_stock_opname_config_locations',
        'config_id',
        'location_id',
        string='Filter By Locations',
        domain=[('usage', '=', 'internal')],
        help='Specific locations allowed for selection in Realtime Stock Opname.'
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        group_user = self.env.ref('realtime_stock_opname.group_realtime_stock_opname_user', raise_if_not_found=False)
        group_apply = self.env.ref('realtime_stock_opname.group_realtime_stock_opname_apply', raise_if_not_found=False)
        group_lock = self.env.ref('realtime_stock_opname.group_realtime_stock_opname_lock', raise_if_not_found=False)
        group_unlock = self.env.ref('realtime_stock_opname.group_realtime_stock_opname_unlock', raise_if_not_found=False)
        group_delete = self.env.ref('realtime_stock_opname.group_realtime_stock_opname_delete', raise_if_not_found=False)
        group_audit = self.env.ref('realtime_stock_opname.group_stock_inventory_audit_user', raise_if_not_found=False)

        if group_user:
            res.update(
                stock_opname_user_ids=[(6, 0, group_user.users.ids)]
            )
        if group_apply:
            res.update(
                stock_opname_apply_user_ids=[(6, 0, group_apply.users.ids)]
            )
        if group_lock:
            res.update(
                stock_opname_lock_user_ids=[(6, 0, group_lock.users.ids)]
            )
        if group_unlock:
            res.update(
                stock_opname_unlock_user_ids=[(6, 0, group_unlock.users.ids)]
            )
        if group_delete:
            res.update(
                stock_opname_delete_user_ids=[(6, 0, group_delete.users.ids)]
            )
        if group_audit:
            res.update(
                stock_inventory_audit_user_ids=[(6, 0, group_audit.users.ids)]
            )

        location_ids_param = self.env['ir.config_parameter'].sudo().get_param('realtime_stock_opname.stock_opname_location_ids', False)
        if location_ids_param:
            loc_ids = [int(x) for x in location_ids_param.split(',') if x.strip().isdigit()]
            res.update(
                stock_opname_location_ids=[(6, 0, loc_ids)]
            )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        group_user = self.env.ref('realtime_stock_opname.group_realtime_stock_opname_user', raise_if_not_found=False)
        group_apply = self.env.ref('realtime_stock_opname.group_realtime_stock_opname_apply', raise_if_not_found=False)
        group_lock = self.env.ref('realtime_stock_opname.group_realtime_stock_opname_lock', raise_if_not_found=False)
        group_unlock = self.env.ref('realtime_stock_opname.group_realtime_stock_opname_unlock', raise_if_not_found=False)
        group_delete = self.env.ref('realtime_stock_opname.group_realtime_stock_opname_delete', raise_if_not_found=False)
        group_audit = self.env.ref('realtime_stock_opname.group_stock_inventory_audit_user', raise_if_not_found=False)

        if group_user:
            group_user.sudo().write({
                'users': [(6, 0, self.stock_opname_user_ids.ids)]
            })
        if group_apply:
            group_apply.sudo().write({
                'users': [(6, 0, self.stock_opname_apply_user_ids.ids)]
            })
        if group_lock:
            group_lock.sudo().write({
                'users': [(6, 0, self.stock_opname_lock_user_ids.ids)]
            })
        if group_unlock:
            group_unlock.sudo().write({
                'users': [(6, 0, self.stock_opname_unlock_user_ids.ids)]
            })
        if group_delete:
            group_delete.sudo().write({
                'users': [(6, 0, self.stock_opname_delete_user_ids.ids)]
            })
        if group_audit:
            group_audit.sudo().write({
                'users': [(6, 0, self.stock_inventory_audit_user_ids.ids)]
            })

        loc_ids_str = ','.join(map(str, self.stock_opname_location_ids.ids)) if self.stock_opname_location_ids else ''
        self.env['ir.config_parameter'].sudo().set_param('realtime_stock_opname.stock_opname_location_ids', loc_ids_str)
