# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class StockQuant(models.Model):
    _inherit = 'stock.quant'

    barcode = fields.Char(
        string='Barcode',
        related='product_id.barcode',
        readonly=True
    )
    categ_id = fields.Many2one(
        'product.category',
        string='Product Category',
        related='product_id.categ_id',
        readonly=True,
        store=True
    )


class StockOpnameDivision(models.Model):
    _name = 'stock.opname.division'
    _description = 'Stock Opname Division'

    name = fields.Char(string='Division Name', required=True)


class RealtimeStockOpname(models.Model):
    _name = 'realtime.stock.opname'
    _description = 'Realtime Stock Opname'
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        states={'draft': [('readonly', False)]},
        default=lambda self: self.env['ir.sequence'].next_by_code('realtime.stock.opname') or _('New')
    )
    date = fields.Datetime(
        string='Date',
        required=True,
        readonly=True,
        states={'draft': [('readonly', False)]},
        default=fields.Datetime.now
    )
    user_id = fields.Many2one(
        'res.users',
        string='Responsible',
        default=lambda self: self.env.user,
        readonly=True
    )
    division_id = fields.Many2one(
        'stock.opname.division',
        string='Division',
        readonly=True,
        states={'draft': [('readonly', False)]}
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        required=True,
        readonly=True,
        states={'draft': [('readonly', False)]},
        domain=lambda self: self._get_location_domain(),
        help="Location where the stock adjustment will be applied."
    )
    barcode_scan = fields.Char(
        string='Scan Barcode',
        readonly=True,
        states={'draft': [('readonly', False)]},
        help="Scan or input product barcode here and press Enter."
    )
    line_ids = fields.One2many(
        'realtime.stock.opname.line',
        'opname_id',
        string='Opname Lines',
        readonly=True,
        states={'draft': [('readonly', False)]}
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done')
    ], string='Status', default='draft', readonly=True, copy=False, tracking=True)

    @api.model
    def _get_location_domain(self):
        domain = [('usage', '=', 'internal')]
        location_ids_param = self.env['ir.config_parameter'].sudo().get_param('realtime_stock_opname.stock_opname_location_ids', False)
        if location_ids_param:
            loc_ids = [int(x) for x in location_ids_param.split(',') if x.strip().isdigit()]
            if loc_ids:
                domain.append(('id', 'in', loc_ids))
        return domain

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('realtime.stock.opname') or _('New')
        return super(RealtimeStockOpname, self).create(vals)

    def action_open_camera_scanner(self):
        self.ensure_one()
        if not self.location_id:
            raise UserError(_("Please select a Location before scanning products."))
        return {
            'type': 'ir.actions.client',
            'tag': 'realtime_stock_opname_camera_scan',
            'target': 'new',
            'context': {
                'active_id': self.id,
                'default_opname_id': self.id,
            }
        }

    def _check_draft_product_conflict(self, product):
        self.ensure_one()
        if not product or not self.location_id:
            return

        # Check if product is already in another draft RSO session at the same location
        other_line = self.env['realtime.stock.opname.line'].search([
            ('product_id', '=', product.id),
            ('opname_id.location_id', '=', self.location_id.id),
            ('opname_id.state', '=', 'draft'),
            ('opname_id', '!=', self.id)
        ], limit=1)

        if other_line:
            creator_name = other_line.create_uid.display_name or other_line.create_uid.name or _("Unknown")
            raise UserError(_(
                "Produk '%s' sudah dibuat pada berkas %s oleh %s (Created by: %s). "
                "Harap tambahkan produk pada berkas %s."
            ) % (product.display_name, other_line.opname_id.name, creator_name, creator_name, other_line.opname_id.name))

        # Check if product is in current RSO and if current user is not the line creator
        existing_line = self.line_ids.filtered(lambda l: l.product_id.id == product.id)
        if existing_line and existing_line[0].create_uid and existing_line[0].create_uid.id != self.env.uid:
            creator_name = existing_line[0].create_uid.display_name or existing_line[0].create_uid.name
            raise UserError(_(
                "Hanya akun %s (yang pertama kali menginput produk '%s' di berkas %s) yang dapat menambah atau mengubah data produk ini."
            ) % (creator_name, product.display_name, self.name))

    def process_scanned_barcode(self, barcode):
        self.ensure_one()
        if not barcode:
            return False

        if not self.location_id:
            raise UserError(_("Please select a Location before scanning products."))

        barcode_str = str(barcode).strip()
        # Search product by barcode
        product = self.env['product.product'].search([('barcode', '=', barcode_str)], limit=1)
        if not product:
            # Fallback to internal reference
            product = self.env['product.product'].search([('default_code', '=', barcode_str)], limit=1)

        if not product:
            raise UserError(_("No product found with barcode or reference '%s'.") % barcode_str)

        # Validate draft conflict and creator permissions
        self._check_draft_product_conflict(product)

        # Check existing line and current stock
        existing_line = self.line_ids.filtered(lambda l: l.product_id.id == product.id)
        existing_opname_qty = existing_line[0].quantity if existing_line else 0.0

        quants = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', '=', self.location_id.id),
            ('lot_id', '=', False),
            ('package_id', '=', False),
            ('owner_id', '=', False)
        ])
        current_qty = sum(quants.mapped('quantity'))

        # Open quantity prompt wizard
        wizard = self.env['realtime.stock.opname.qty.wizard'].create({
            'opname_id': self.id,
            'product_id': product.id,
            'current_qty': current_qty,
            'existing_opname_qty': existing_opname_qty,
            'quantity': 1.0,
        })
        view_id = self.env.ref('realtime_stock_opname.view_realtime_stock_opname_qty_wizard_form').id
        return {
            'name': _('Input Stock Quantity'),
            'type': 'ir.actions.act_window',
            'res_model': 'realtime.stock.opname.qty.wizard',
            'res_id': wizard.id,
            'view_id': view_id,
            'views': [(view_id, 'form')],
            'view_mode': 'form',
            'target': 'new',
        }

    def action_process_barcode(self):
        self.ensure_one()
        if not self.barcode_scan:
            return
        barcode = self.barcode_scan
        self.barcode_scan = False
        return self.process_scanned_barcode(barcode)

    @api.onchange('barcode_scan')
    def _onchange_barcode_scan(self):
        if not self.barcode_scan:
            return

        if not self.location_id:
            self.barcode_scan = False
            return {
                'warning': {
                    'title': _('Location Required'),
                    'message': _('Please select a Location before scanning products.')
                }
            }

        # Search product by barcode
        product = self.env['product.product'].search([('barcode', '=', self.barcode_scan.strip())], limit=1)
        if not product:
            # Fallback to internal reference in case barcode matches that
            product = self.env['product.product'].search([('default_code', '=', self.barcode_scan.strip())], limit=1)

        if not product:
            barcode_scanned = self.barcode_scan
            self.barcode_scan = False
            return {
                'warning': {
                    'title': _('Product Not Found'),
                    'message': _('No product found with barcode or reference "%s".') % barcode_scanned
                }
            }

        try:
            self._check_draft_product_conflict(product)
        except UserError as e:
            self.barcode_scan = False
            return {
                'warning': {
                    'title': _('Product Conflict'),
                    'message': str(e)
                }
            }

        # Find if product already exists in current lines
        existing_line = self.line_ids.filtered(lambda l: l.product_id.id == product.id)
        if existing_line:
            # If product exists, increment quantity by 1
            existing_line[0].quantity += 1.0
        else:
            # Fetch current system quantity at this location
            quants = self.env['stock.quant'].search([
                ('product_id', '=', product.id),
                ('location_id', '=', self.location_id.id),
                ('lot_id', '=', False),
                ('package_id', '=', False),
                ('owner_id', '=', False)
            ])
            current_qty = sum(quants.mapped('quantity'))

            # Create a new line
            line_vals = {
                'product_id': product.id,
                'current_qty': current_qty,
                'quantity': 1.0,
            }
            new_line = self.env['realtime.stock.opname.line'].new(line_vals)
            self.line_ids = self.line_ids + new_line

        # Reset scanning field for the next scan
        self.barcode_scan = False

    def action_apply(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("There are no lines to apply."))

        # Update stock quantity for each line using Total Qty
        for line in self.line_ids:
            quant = self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', self.location_id.id),
                ('lot_id', '=', False),
                ('package_id', '=', False),
                ('owner_id', '=', False)
            ], limit=1)

            if quant:
                quant.inventory_quantity = line.total_qty
            else:
                quant = self.env['stock.quant'].create({
                    'product_id': line.product_id.id,
                    'location_id': self.location_id.id,
                    'inventory_quantity': line.total_qty,
                })

            # Apply inventory adjustment
            quant.action_apply_inventory()

        self.state = 'done'

    def action_lock(self):
        self.ensure_one()
        self.state = 'done'

    def action_unlock(self):
        self.ensure_one()
        self.state = 'draft'


class RealtimeStockOpnameQtyWizard(models.TransientModel):
    _name = 'realtime.stock.opname.qty.wizard'
    _description = 'Stock Opname Quantity Wizard'

    opname_id = fields.Many2one('realtime.stock.opname', string='Opname', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True, readonly=True)
    barcode = fields.Char(string='Barcode', related='product_id.barcode', readonly=True)
    categ_id = fields.Many2one('product.category', string='Product Category', related='product_id.categ_id', readonly=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure', related='product_id.uom_id', readonly=True)
    current_qty = fields.Float(string='Current Stock Qty', readonly=True)
    existing_opname_qty = fields.Float(string='Already Input Qty', readonly=True)
    quantity = fields.Float(string='Scanned / Added Quantity', required=True, default=1.0)

    def action_confirm(self):
        self.ensure_one()
        self.opname_id._check_draft_product_conflict(self.product_id)
        existing_line = self.opname_id.line_ids.filtered(lambda l: l.product_id.id == self.product_id.id)
        if existing_line:
            new_stock_qty = existing_line[0].quantity + self.quantity
            existing_line[0].quantity = new_stock_qty
            opname_line = existing_line[0]
        else:
            new_stock_qty = self.quantity
            opname_line = self.env['realtime.stock.opname.line'].create({
                'opname_id': self.opname_id.id,
                'product_id': self.product_id.id,
                'current_qty': self.current_qty,
                'quantity': new_stock_qty,
            })

        # Apply immediate real-time stock adjustment to stock.quant using total_qty (Stock Qty - Sold Qty)
        adjust_qty = opname_line.total_qty
        quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', '=', self.opname_id.location_id.id),
            ('lot_id', '=', False),
            ('package_id', '=', False),
            ('owner_id', '=', False)
        ], limit=1)

        if quant:
            quant.inventory_quantity = adjust_qty
        else:
            quant = self.env['stock.quant'].create({
                'product_id': self.product_id.id,
                'location_id': self.opname_id.location_id.id,
                'inventory_quantity': adjust_qty,
            })

        quant.action_apply_inventory()

        return {'type': 'ir.actions.act_window_close'}


class RealtimeStockOpnameLine(models.Model):
    _name = 'realtime.stock.opname.line'
    _description = 'Realtime Stock Opname Line'

    @api.constrains('product_id', 'opname_id')
    def _check_draft_line_conflict(self):
        for line in self:
            if not line.product_id or not line.opname_id or not line.opname_id.location_id:
                continue

            # Check if product exists in another draft RSO session at same location
            other_line = self.search([
                ('product_id', '=', line.product_id.id),
                ('opname_id.location_id', '=', line.opname_id.location_id.id),
                ('opname_id.state', '=', 'draft'),
                ('id', '!=', line.id),
                ('opname_id', '!=', line.opname_id.id)
            ], limit=1)

            if other_line:
                creator_name = other_line.create_uid.display_name or other_line.create_uid.name or _("Unknown")
                raise UserError(_(
                    "Produk '%s' sudah dibuat pada berkas %s oleh %s (Created by: %s). "
                    "Harap tambahkan produk pada berkas %s."
                ) % (line.product_id.display_name, other_line.opname_id.name, creator_name, creator_name, other_line.opname_id.name))

    opname_id = fields.Many2one(
        'realtime.stock.opname',
        string='Opname Reference',
        ondelete='cascade',
        required=True
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        readonly=True
    )
    product_name = fields.Char(
        string='Product Name',
        related='product_id.name',
        readonly=True
    )
    barcode = fields.Char(
        string='Barcode',
        related='product_id.barcode',
        readonly=True
    )
    categ_id = fields.Many2one(
        'product.category',
        string='Product Category',
        related='product_id.categ_id',
        readonly=True,
        store=True
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        related='opname_id.location_id',
        readonly=True,
        store=True
    )
    division_id = fields.Many2one(
        'stock.opname.division',
        string='Division',
        related='opname_id.division_id',
        readonly=True,
        store=True
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        related='product_id.uom_id',
        readonly=True
    )
    cost_price = fields.Float(
        string='Cost',
        related='product_id.standard_price',
        readonly=True,
        store=True
    )
    total_cost = fields.Float(
        string='T. Cost',
        compute='_compute_total_cost',
        store=True,
        readonly=True,
        help="Calculated as Stock Qty x Cost."
    )

    @api.depends('quantity', 'cost_price')
    def _compute_total_cost(self):
        for line in self:
            line.total_cost = line.quantity * line.cost_price
    lst_price = fields.Float(
        string='Sales Price',
        related='product_id.lst_price',
        readonly=True,
        store=True
    )
    total_sales_price = fields.Float(
        string='T. Sales Price',
        compute='_compute_total_sales_price',
        store=True,
        readonly=True,
        help="Calculated as Stock Qty x Sales Price."
    )

    @api.depends('quantity', 'lst_price')
    def _compute_total_sales_price(self):
        for line in self:
            line.total_sales_price = line.quantity * line.lst_price
    user_id = fields.Many2one(
        'res.users',
        string='Responsible',
        related='opname_id.user_id',
        readonly=True,
        store=True
    )
    reference = fields.Char(
        string='Reference',
        related='opname_id.name',
        readonly=True,
        store=True
    )
    date = fields.Datetime(
        string='Date',
        related='opname_id.date',
        readonly=True,
        store=True
    )
    sold_qty = fields.Float(
        string='Sold Qty',
        digits='Product Unit of Measure',
        compute='_compute_sold_qty',
        readonly=True,
        help="Quantity sold after the session Date creation."
    )
    internal_transfer_qty = fields.Float(
        string='Internal Transfers Qty',
        digits='Product Unit of Measure',
        compute='_compute_internal_transfer_qty',
        readonly=True,
        help="Net internal transfers (Out minus In) completed after the session Date creation."
    )
    current_qty = fields.Float(
        string='Current Qty',
        digits='Product Unit of Measure',
        readonly=True,
        help="Current quantity of this product in the selected location."
    )
    quantity = fields.Float(
        string='Stock Qty',
        digits='Product Unit of Measure',
        required=True,
        default=1.0,
        help="Input the new actual stock quantity."
    )
    difference_qty = fields.Float(
        string='Difference Qty',
        digits='Product Unit of Measure',
        compute='_compute_discrepancy_data',
        store=True,
        readonly=True,
        help="Result of Stock Qty minus Current Qty."
    )
    discrepancy_category = fields.Selection([
        ('equal_0', '= 0'),
        ('greater_1', '> 1'),
        ('less_minus_1', '< -1'),
    ], string='Discrepancy Category', compute='_compute_discrepancy_data', store=True, readonly=True)

    compliance_status = fields.Selection([
        ('compliant', 'Sesuai Stok'),
        ('non_compliant', 'Tidak Sesuai Stok'),
    ], string='Stock Status', compute='_compute_discrepancy_data', store=True, readonly=True)

    sp_x_stock_qty = fields.Float(
        string='SP x Stock Qty',
        compute='_compute_sp_x_stock_qty',
        store=True,
        readonly=True,
        help="Calculated as Sales Price x Stock Qty."
    )

    @api.depends('lst_price', 'quantity')
    def _compute_sp_x_stock_qty(self):
        for line in self:
            line.sp_x_stock_qty = line.lst_price * line.quantity

    sp_x_difference_qty = fields.Float(
        string='SP x Difference Qty',
        compute='_compute_sp_x_difference_qty',
        store=True,
        readonly=True,
        help="Calculated as Sales Price x Difference Qty."
    )

    @api.depends('lst_price', 'difference_qty')
    def _compute_sp_x_difference_qty(self):
        for line in self:
            line.sp_x_difference_qty = line.lst_price * line.difference_qty

    @api.depends('quantity', 'current_qty')
    def _compute_discrepancy_data(self):
        for line in self:
            if line.current_qty < 0:
                diff = line.quantity + line.current_qty
            else:
                diff = line.quantity - line.current_qty
            line.difference_qty = diff
            if diff == 0:
                line.discrepancy_category = 'equal_0'
                line.compliance_status = 'compliant'
            elif diff > 0:
                line.discrepancy_category = 'greater_1'
                line.compliance_status = 'non_compliant'
            else:
                line.discrepancy_category = 'less_minus_1'
                line.compliance_status = 'non_compliant'

    total_qty = fields.Float(
        string='Total Qty',
        digits='Product Unit of Measure',
        compute='_compute_total_qty',
        readonly=True,
        help="Result of Stock Qty minus Sold Qty and Internal Transfers Qty."
    )

    @api.depends('quantity', 'sold_qty', 'internal_transfer_qty')
    def _compute_total_qty(self):
        for line in self:
            line.total_qty = line.quantity - line.sold_qty - line.internal_transfer_qty

    @api.model
    def action_open_products_not_recorded(self):
        recorded_lines = self.search([])
        recorded_pairs = [(line.product_id.id, line.opname_id.location_id.id) for line in recorded_lines if line.product_id and line.opname_id.location_id]

        domain = [('location_id.usage', '=', 'internal')]
        if recorded_pairs:
            recorded_quant_ids = []
            all_internal_quants = self.env['stock.quant'].search([('location_id.usage', '=', 'internal')])
            for quant in all_internal_quants:
                if (quant.product_id.id, quant.location_id.id) in recorded_pairs:
                    recorded_quant_ids.append(quant.id)
            if recorded_quant_ids:
                domain.append(('id', 'not in', recorded_quant_ids))

        tree_view_id = self.env.ref('realtime_stock_opname.view_product_not_recorded_tree').id
        form_view_id = self.env.ref('realtime_stock_opname.view_product_not_recorded_form').id
        search_view_id = self.env.ref('realtime_stock_opname.view_product_not_recorded_search').id
        return {
            'name': _('Product Not Recorded in Stock Take'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.quant',
            'views': [(tree_view_id, 'tree'), (form_view_id, 'form')],
            'view_mode': 'tree,form',
            'search_view_id': search_view_id,
            'domain': domain,
            'context': dict(self.env.context, search_default_groupby_location=1),
        }

    @api.depends('product_id', 'opname_id.date', 'opname_id.location_id')
    def _compute_sold_qty(self):
        lines_by_opname = {}
        for line in self:
            if not line.product_id or not line.opname_id.location_id or not line.opname_id.date:
                line.sold_qty = 0.0
                continue
            lines_by_opname.setdefault(line.opname_id, []).append(line)

        if not lines_by_opname:
            return

        cr = self.env.cr

        # Check POS table existence
        cr.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name = 'pos_order'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name = 'pos_order_line'
            )
        """)
        has_pos = cr.fetchone()[0]

        pos_config_stock_loc = False
        pos_config_picking_type = False
        pos_order_picking_id = False
        if has_pos:
            cr.execute("""
                SELECT
                    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pos_config' AND column_name='stock_location_id'),
                    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pos_config' AND column_name='picking_type_id'),
                    EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='pos_order' AND column_name='picking_id')
            """)
            pos_config_stock_loc, pos_config_picking_type, pos_order_picking_id = cr.fetchone()

        cr.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns WHERE table_name='stock_move' AND column_name='pos_line_id'
            )
        """)
        has_pos_line_id = cr.fetchone()[0]

        for opname, lines in lines_by_opname.items():
            product_ids = tuple(set(l.product_id.id for l in lines))
            if not product_ids:
                for line in lines:
                    line.sold_qty = 0.0
                continue

            location_id = opname.location_id.id
            start_date = opname.date

            sold_qty_by_product = {pid: 0.0 for pid in product_ids}
            pos_counted_move_ids = set()

            # 1. POS sales computation using direct SQL to avoid ORM loading unmigrated table columns
            if has_pos:
                where_loc_clauses = []
                params_pos = [product_ids, start_date]

                if pos_config_stock_loc:
                    where_loc_clauses.append("cfg.stock_location_id = %s")
                    params_pos.append(location_id)
                if pos_config_picking_type:
                    where_loc_clauses.append("pt.default_location_src_id = %s")
                    params_pos.append(location_id)

                loc_condition = " OR ".join(where_loc_clauses) if where_loc_clauses else "1=0"

                query_pos = f"""
                    SELECT pol.product_id, SUM(pol.qty)
                    FROM pos_order_line pol
                    JOIN pos_order po ON po.id = pol.order_id
                    LEFT JOIN pos_session ps ON ps.id = po.session_id
                    LEFT JOIN pos_config cfg ON cfg.id = ps.config_id
                    LEFT JOIN stock_picking_type pt ON pt.id = cfg.picking_type_id
                    WHERE pol.product_id IN %s
                      AND po.date_order >= %s
                      AND po.state IN ('draft', 'paid', 'done', 'invoiced')
                      AND ({loc_condition})
                    GROUP BY pol.product_id
                """
                cr.execute(query_pos, tuple(params_pos))
                for pid, qty_sum in cr.fetchall():
                    if pid in sold_qty_by_product:
                        sold_qty_by_product[pid] += qty_sum or 0.0

                if pos_order_picking_id and loc_condition != "1=0":
                    query_moves = f"""
                        SELECT sm.id
                        FROM stock_move sm
                        JOIN pos_order po ON po.picking_id = sm.picking_id
                        LEFT JOIN pos_session ps ON ps.id = po.session_id
                        LEFT JOIN pos_config cfg ON cfg.id = ps.config_id
                        LEFT JOIN stock_picking_type pt ON pt.id = cfg.picking_type_id
                        WHERE sm.product_id IN %s
                          AND po.date_order >= %s
                          AND po.state IN ('draft', 'paid', 'done', 'invoiced')
                          AND ({loc_condition})
                    """
                    cr.execute(query_moves, tuple(params_pos))
                    for (m_id,) in cr.fetchall():
                        pos_counted_move_ids.add(m_id)

            # 2. Direct stock moves to customer using direct SQL
            where_moves = [
                "sm.product_id IN %s",
                "sm.location_id = %s",
                "dest_loc.usage = 'customer'",
                "sm.state = 'done'",
                "sm.date >= %s"
            ]
            params_stock = [product_ids, location_id, start_date]

            if has_pos_line_id:
                where_moves.append("sm.pos_line_id IS NULL")

            if pos_counted_move_ids:
                where_moves.append("sm.id NOT IN %s")
                params_stock.append(tuple(pos_counted_move_ids))

            if has_pos and pos_order_picking_id:
                where_moves.append("""
                    NOT EXISTS (
                        SELECT 1 FROM pos_order po_old
                        WHERE po_old.picking_id = sm.picking_id
                          AND po_old.date_order < %s
                    )
                """)
                params_stock.append(start_date)

            where_str = " AND ".join(where_moves)
            move_query = f"""
                SELECT sm.product_id, SUM(sm.product_uom_qty)
                FROM stock_move sm
                JOIN stock_location dest_loc ON dest_loc.id = sm.location_dest_id
                WHERE {where_str}
                GROUP BY sm.product_id
            """
            cr.execute(move_query, tuple(params_stock))
            for pid, qty_sum in cr.fetchall():
                if pid in sold_qty_by_product:
                    sold_qty_by_product[pid] += qty_sum or 0.0

            for line in lines:
                line.sold_qty = sold_qty_by_product.get(line.product_id.id, 0.0)

    @api.depends('product_id', 'opname_id.date', 'opname_id.location_id')
    def _compute_internal_transfer_qty(self):
        lines_by_opname = {}
        for line in self:
            if not line.product_id or not line.opname_id.location_id or not line.opname_id.date:
                line.internal_transfer_qty = 0.0
                continue
            lines_by_opname.setdefault(line.opname_id, []).append(line)

        if not lines_by_opname:
            return

        cr = self.env.cr

        for opname, lines in lines_by_opname.items():
            product_ids = tuple(set(l.product_id.id for l in lines))
            if not product_ids:
                for line in lines:
                    line.internal_transfer_qty = 0.0
                continue

            location_id = opname.location_id.id
            start_date = opname.date

            transfer_qty_by_product = {pid: 0.0 for pid in product_ids}

            # Moves OUT to internal locations
            query_out = """
                SELECT sm.product_id, SUM(sm.product_uom_qty)
                FROM stock_move sm
                JOIN stock_location dest_loc ON dest_loc.id = sm.location_dest_id
                WHERE sm.product_id IN %s
                  AND sm.location_id = %s
                  AND dest_loc.usage = 'internal'
                  AND sm.state = 'done'
                  AND sm.date >= %s
                GROUP BY sm.product_id
            """
            cr.execute(query_out, (product_ids, location_id, start_date))
            for pid, qty_sum in cr.fetchall():
                if pid in transfer_qty_by_product:
                    transfer_qty_by_product[pid] += qty_sum or 0.0

            # Moves IN from internal locations
            query_in = """
                SELECT sm.product_id, SUM(sm.product_uom_qty)
                FROM stock_move sm
                JOIN stock_location src_loc ON src_loc.id = sm.location_id
                WHERE sm.product_id IN %s
                  AND sm.location_dest_id = %s
                  AND src_loc.usage = 'internal'
                  AND sm.state = 'done'
                  AND sm.date >= %s
                GROUP BY sm.product_id
            """
            cr.execute(query_in, (product_ids, location_id, start_date))
            for pid, qty_sum in cr.fetchall():
                if pid in transfer_qty_by_product:
                    transfer_qty_by_product[pid] -= qty_sum or 0.0

            for line in lines:
                line.internal_transfer_qty = transfer_qty_by_product.get(line.product_id.id, 0.0)
