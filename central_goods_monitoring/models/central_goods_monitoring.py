from odoo import models, fields, api, _
import xmlrpc.client
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)

class CentralGoodsMonitoring(models.Model):
    _name = 'central.goods.monitoring'
    _description = 'Central Goods Monitoring'

    name = fields.Char(string='Reference', readonly=True)
    remote_id = fields.Integer(string='Remote ID', readonly=True, index=True)
    responsible_name = fields.Char(string='Responsible', readonly=True)
    source_location_name = fields.Char(string='Source Location', readonly=True)
    request_date = fields.Date(string='Request Date', readonly=True)
    destination_location_name = fields.Char(string='Destination Location', readonly=True)
    state = fields.Char(string='Status', readonly=True)
    local_state = fields.Selection([
        ('draft', 'Draft'),
        ('validated', 'Validated')
    ], string='Branch Status', default='draft', readonly=True)
    branch_stock_source_id = fields.Many2one('stock.location', string='Branch Stock Source Location')
    allowed_branch_stock_source_ids = fields.Many2many('stock.location',
                                                       compute='_compute_allowed_branch_stock_source_ids',
                                                       store=False)
    line_ids = fields.One2many('central.goods.monitoring.line', 'monitoring_id', string='Product Lines')

    def _compute_allowed_branch_stock_source_ids(self):
        ICPSudo = self.env['ir.config_parameter'].sudo()
        location_ids_str = ICPSudo.get_param('central_goods_monitoring.filter_branch_source_location_ids')

        location_ids = []
        if location_ids_str:
            try:
                location_ids = [int(x) for x in location_ids_str.split(',') if x.strip()]
            except (ValueError, TypeError):
                location_ids = []

        if location_ids:
            allowed_locations = self.env['stock.location'].sudo().browse(location_ids).exists()
        else:
            allowed_locations = self.env['stock.location'].sudo().search([('usage', '=', 'internal')])

        for record in self:
            record.allowed_branch_stock_source_ids = allowed_locations.with_env(self.env)

    def action_validate(self):
        self.ensure_one()
        if not self.branch_stock_source_id:
            raise UserError(_("Please select a Branch Stock Source Location before validating."))

        if self.local_state == 'validated':
            raise UserError(_("This record has already been validated."))

        # Create stock moves to increase stock
        # Source location for receipt usually a virtual location
        picking_type = self.env['stock.picking.type'].search([('code', '=', 'incoming')], limit=1)
        source_location = picking_type.default_location_src_id or self.env.ref('stock.stock_location_suppliers', raise_if_not_found=False)

        if not source_location:
            # Fallback to inventory loss if no supplier location found
            source_location = self.env['stock.location'].search([('usage', '=', 'inventory')], limit=1)

        moves = self.env['stock.move']
        for line in self.line_ids:
            if line.quantity_in <= 0:
                continue

            # Find product by barcode
            product = self.env['product.product'].search([('barcode', '=', line.barcode)], limit=1)
            if not product:
                # Try matching by name if barcode fails
                product = self.env['product.product'].search([('name', '=', line.product_name)], limit=1)

            if not product:
                raise UserError(_("Product with barcode %s not found in local database.") % line.barcode)

            move = self.env['stock.move'].create({
                'name': _('Receipt from %s') % self.name,
                'product_id': product.id,
                'product_uom_qty': line.quantity_in,
                'product_uom': product.uom_id.id,
                'location_id': source_location.id,
                'location_dest_id': self.branch_stock_source_id.id,
            })
            moves |= move

        if moves:
            moves._action_confirm()
            moves._action_assign()
            # Set quantities done
            for move in moves:
                for line in move.move_line_ids:
                    line.qty_done = line.product_uom_qty
            moves._action_done()

        # Update status on remote server
        ICPSudo = self.env['ir.config_parameter'].sudo()
        url = ICPSudo.get_param('central_goods_monitoring.remote_server_url')
        db = ICPSudo.get_param('central_goods_monitoring.remote_server_db')
        username = ICPSudo.get_param('central_goods_monitoring.remote_server_username')
        password = ICPSudo.get_param('central_goods_monitoring.remote_server_password')

        if all([url, db, username, password]):
            try:
                common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
                uid = common.authenticate(db, username, password, {})
                models_proxy = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

                # Update main record status
                models_proxy.execute_kw(db, uid, password, 'goods.out.branch', 'write', [[self.remote_id], {'branch_status': 'Validated'}])

                # Update line quantities on Computer A
                for line in self.line_ids:
                    if line.remote_line_id:
                        models_proxy.execute_kw(db, uid, password, 'goods.out.branch.line', 'write', [[line.remote_line_id], {'quantity_in': line.quantity_in}])

            except Exception as e:
                _logger.error("Failed to update remote status/quantities: %s", str(e))
                # We don't raise UserError here to not block local validation if remote update fails

        self.write({'local_state': 'validated'})
        return True

    @api.model
    def action_fetch_data(self):
        _logger.info("Starting manual fetch of data from remote server.")
        ICPSudo = self.env['ir.config_parameter'].sudo()
        url = ICPSudo.get_param('central_goods_monitoring.remote_server_url')
        db = ICPSudo.get_param('central_goods_monitoring.remote_server_db')
        username = ICPSudo.get_param('central_goods_monitoring.remote_server_username')
        password = ICPSudo.get_param('central_goods_monitoring.remote_server_password')
        dest_location_name = ICPSudo.get_param('central_goods_monitoring.destination_location_name')

        source_location_ids_str = ICPSudo.get_param('central_goods_monitoring.filter_branch_source_location_ids')
        source_location_names = []
        if source_location_ids_str:
            source_location_ids = [int(id) for id in source_location_ids_str.split(',') if id]
            source_locations = self.env['stock.location'].browse(source_location_ids)
            source_location_names = source_locations.mapped('name')

        if not all([url, db, username, password]):
            raise UserError(_("Please configure remote server settings first."))

        try:
            common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
            uid = common.authenticate(db, username, password, {})
            models_proxy = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

            # Fetch Goods Out to Branch records
            _logger.info("Fetching data from remote server: %s", url)
            domain = [('state', '=', 'done')]
            if dest_location_name:
                _logger.info("Filtering by destination location: %s", dest_location_name)
                domain.append(('destination_location_id.name', '=', dest_location_name))

            if source_location_names:
                _logger.info("Filtering by source location names: %s", source_location_names)
                domain.append(('source_location_id.name', 'in', source_location_names))

            remote_records = models_proxy.execute_kw(db, uid, password, 'goods.out.branch', 'search_read', [domain], {
                'fields': ['id', 'name', 'responsible_id', 'source_location_id', 'request_date', 'destination_location_id', 'state']
            })
            _logger.info("Found %s records on remote server.", len(remote_records))

            synced_count = 0
            for rec in remote_records:
                _logger.info("Syncing remote record ID %s (%s)", rec['id'], rec['name'])
                existing = self.search([('remote_id', '=', rec['id'])], limit=1)
                synced_count += 1
                vals = {
                    'name': rec['name'],
                    'remote_id': rec['id'],
                    'responsible_name': rec['responsible_id'][1] if rec['responsible_id'] else '',
                    'source_location_name': rec['source_location_id'][1] if rec['source_location_id'] else '',
                    'request_date': rec['request_date'],
                    'destination_location_name': rec['destination_location_id'][1] if rec['destination_location_id'] else '',
                    'state': rec['state'],
                }

                if existing:
                    existing.write(vals)
                    monitoring_id = existing
                else:
                    monitoring_id = self.create(vals)
                    # Update remote status to Draft on first sync
                    try:
                        models_proxy.execute_kw(db, uid, password, 'goods.out.branch', 'write', [[rec['id']], {'branch_status': 'Draft'}])
                    except Exception as e:
                        _logger.error("Failed to update initial remote status: %s", str(e))

                # Sync lines: if local_state is draft, we can update them.
                if monitoring_id.local_state == 'draft':
                    # Fetch lines for this record
                    remote_lines = models_proxy.execute_kw(db, uid, password, 'goods.out.branch.line', 'search_read', [[['goods_out_id', '=', rec['id']]]], {
                        'fields': ['id', 'product_id', 'barcode', 'category_id', 'uom_id', 'quantity_out']
                    })

                    # Clear old lines and add new ones (simple sync)
                    monitoring_id.line_ids.unlink()
                    line_vals = []
                    for line in remote_lines:
                        line_vals.append((0, 0, {
                            'product_name': line['product_id'][1] if line['product_id'] else '',
                            'barcode': line['barcode'],
                            'category_name': line['category_id'][1] if line['category_id'] else '',
                            'uom_name': line['uom_id'][1] if line['uom_id'] else '',
                            'quantity_out': line['quantity_out'],
                            'quantity_in': line['quantity_out'], # Default quantity_in to quantity_out
                            'remote_line_id': line['id'],
                        }))
                    monitoring_id.write({'line_ids': line_vals})

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Sync Complete'),
                    'message': _('Successfully synchronized %s records.') % synced_count,
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                }
            }

        except Exception as e:
            _logger.error("Sync failed: %s", str(e))
            raise UserError(_("Error connecting to remote server: %s") % str(e))

class CentralGoodsMonitoringLine(models.Model):
    _name = 'central.goods.monitoring.line'
    _description = 'Central Goods Monitoring Line'

    monitoring_id = fields.Many2one('central.goods.monitoring', string='Monitoring Reference', ondelete='cascade')
    remote_line_id = fields.Integer(string='Remote Line ID', readonly=True)
    product_name = fields.Char(string='Product Name')
    barcode = fields.Char(string='Barcode')
    category_name = fields.Char(string='Product Category')
    uom_name = fields.Char(string='UOM')
    quantity_out = fields.Float(string='Quantity Out', readonly=True)
    quantity_in = fields.Float(string='Quantity In')
    is_new_product = fields.Boolean(
        string='Is New Product',
        compute='_compute_is_new_product',
        search='_search_is_new_product'
    )

    def _compute_is_new_product(self):
        for line in self:
            product = False
            if line.barcode:
                product = self.env['product.product'].search([('barcode', '=', line.barcode)], limit=1)
            if not product and line.product_name:
                product = self.env['product.product'].search([('name', '=', line.product_name)], limit=1)
            line.is_new_product = not bool(product)

    def _search_is_new_product(self, operator, value):
        positive = (operator in ('=', 'in') and value) or (operator in ('!=', 'not in') and not value)

        products = self.env['product.product'].sudo().search_read([], ['barcode', 'name'])
        existing_barcodes = {p['barcode'] for p in products if p['barcode']}
        existing_names = {p['name'] for p in products if p['name']}

        all_lines = self.sudo().search_read([], ['id', 'barcode', 'product_name'])
        existing_line_ids = [
            l['id'] for l in all_lines
            if (l['barcode'] and l['barcode'] in existing_barcodes) or
               (l['product_name'] and l['product_name'] in existing_names)
        ]

        if positive:
            return [('id', 'not in', existing_line_ids)]
        else:
            return [('id', 'in', existing_line_ids)]

    @api.constrains('quantity_in', 'quantity_out')
    def _check_quantity_in(self):
        for line in self:
            if line.quantity_in > line.quantity_out:
                raise ValidationError(_("Inputan Nilai Stok Barang Quantity In Melebihi Nilai Stok Barang Quantity Out"))
