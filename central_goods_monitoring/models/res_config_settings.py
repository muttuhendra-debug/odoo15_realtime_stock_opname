from odoo import models, fields, api, _
import xmlrpc.client

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    remote_server_url = fields.Char(string='Remote Server URL', config_parameter='central_goods_monitoring.remote_server_url')
    remote_server_db = fields.Char(string='Remote Server Database', config_parameter='central_goods_monitoring.remote_server_db')
    remote_server_username = fields.Char(string='Remote Server Username', config_parameter='central_goods_monitoring.remote_server_username')
    remote_server_password = fields.Char(string='Remote Server Password', config_parameter='central_goods_monitoring.remote_server_password')
    destination_location_name = fields.Char(string='Destination Location Name', config_parameter='central_goods_monitoring.destination_location_name')
    filter_branch_source_location_ids = fields.Many2many(
        'stock.location',
        'res_config_settings_central_goods_stock_location_rel',
        'config_id', 'location_id',
        string='Filter By Branch Stock Source Location'
    )

    connection_status = fields.Selection([
        ('connected', 'Connected'),
        ('not_connected', 'Not Connected')
    ], string='Connection Status', config_parameter='central_goods_monitoring.connection_status')

    def action_test_connection(self):
        if not all([self.remote_server_url, self.remote_server_db, self.remote_server_username, self.remote_server_password]):
            self.connection_status = 'not_connected'
        else:
            try:
                common = xmlrpc.client.ServerProxy(f'{self.remote_server_url}/xmlrpc/2/common')
                uid = common.authenticate(self.remote_server_db, self.remote_server_username, self.remote_server_password, {})
                if uid:
                    self.connection_status = 'connected'
                else:
                    self.connection_status = 'not_connected'
            except Exception:
                self.connection_status = 'not_connected'

        # Force save to system parameters so it persists immediately
        self.env['ir.config_parameter'].sudo().set_param('central_goods_monitoring.connection_status', self.connection_status)

        if self.connection_status == 'connected':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Successfully connected to the remote server.'),
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Failed'),
                    'message': _('Could not connect to the remote server. Please check your credentials and URL.'),
                    'type': 'danger',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                }
            }

    def action_fetch_data(self):
        self.set_values()
        return self.env['central.goods.monitoring'].action_fetch_data()

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        ICPSudo = self.env['ir.config_parameter'].sudo()
        location_ids_str = ICPSudo.get_param('central_goods_monitoring.filter_branch_source_location_ids')
        if location_ids_str:
            location_ids = [int(id) for id in location_ids_str.split(',') if id]
            res.update(
                filter_branch_source_location_ids=[(6, 0, location_ids)],
            )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        ICPSudo = self.env['ir.config_parameter'].sudo()
        location_ids_str = ','.join(map(str, self.filter_branch_source_location_ids.ids))
        ICPSudo.set_param('central_goods_monitoring.filter_branch_source_location_ids', location_ids_str)
