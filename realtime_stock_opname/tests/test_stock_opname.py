# -*- coding: utf-8 -*-
from odoo.tests import common
from odoo.exceptions import UserError
from datetime import datetime, timedelta

class TestRealtimeStockOpname(common.TransactionCase):

    @classmethod
    def setUpClass(cls):
        super(TestRealtimeStockOpname, cls).setUpClass()
        # Create test products
        cls.product_a = cls.env['product.product'].create({
            'name': 'Test Opname Product A',
            'type': 'product',
            'barcode': '1234567890',
            'default_code': 'REF-123',
        })
        cls.product_b = cls.env['product.product'].create({
            'name': 'Test Opname Product B',
            'type': 'product',
            'barcode': '0987654321',
            'default_code': 'REF-456',
        })
        # Get internal location & customer location
        cls.location = cls.env['stock.location'].search([('usage', '=', 'internal')], limit=1)
        if not cls.location:
            cls.location = cls.env['stock.location'].create({
                'name': 'Test Internal Location',
                'usage': 'internal',
            })
        cls.customer_location = cls.env['stock.location'].search([('usage', '=', 'customer')], limit=1)
        if not cls.customer_location:
            cls.customer_location = cls.env['stock.location'].create({
                'name': 'Test Customer Location',
                'usage': 'customer',
            })

    def test_01_barcode_scan_success(self):
        """Test barcode scan adds the product successfully with correct initial current_qty and quantity"""
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
        })

        # Simulate scanning product barcode
        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        self.assertEqual(len(opname.line_ids), 1, "There should be 1 stock opname line.")
        line = opname.line_ids[0]
        self.assertEqual(line.product_id, self.product_a)
        self.assertEqual(line.barcode, '1234567890')
        self.assertEqual(line.quantity, 1.0)
        self.assertEqual(line.current_qty, 0.0)
        self.assertEqual(line.sold_qty, 0.0)

    def test_02_barcode_scan_increment(self):
        """Test scanning the same product multiple times increments its quantity"""
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
        })

        # Scan once
        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        # Scan again
        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        self.assertEqual(len(opname.line_ids), 1, "There should still be only 1 stock opname line.")
        line = opname.line_ids[0]
        self.assertEqual(line.quantity, 2.0)

    def test_03_multiple_different_products_scan(self):
        """Test scanning multiple different products in sequence keeps both lines in One2many"""
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
        })

        # Scan Product A
        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        # Scan Product B
        opname.barcode_scan = '0987654321'
        opname._onchange_barcode_scan()

        self.assertEqual(len(opname.line_ids), 2, "There should be 2 stock opname lines after scanning two different products.")
        products_scanned = opname.line_ids.mapped('product_id')
        self.assertIn(self.product_a, products_scanned)
        self.assertIn(self.product_b, products_scanned)

    def test_04_camera_process_scanned_barcode_additive_accumulation(self):
        """Test camera process_scanned_barcode additively accumulates quantity (2 + 3 = 5)"""
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
        })

        # First scan: Set quantity to 2
        action1 = opname.process_scanned_barcode('1234567890')
        wizard1 = self.env['realtime.stock.opname.qty.wizard'].browse(action1.get('res_id'))
        wizard1.quantity = 2.0
        wizard1.action_confirm()

        self.assertEqual(len(opname.line_ids), 1)
        self.assertEqual(opname.line_ids[0].quantity, 2.0)

        # Second scan of same product: Input 3 -> Total should be 2 + 3 = 5
        action2 = opname.process_scanned_barcode('1234567890')
        wizard2 = self.env['realtime.stock.opname.qty.wizard'].browse(action2.get('res_id'))
        self.assertEqual(wizard2.existing_opname_qty, 2.0)
        wizard2.quantity = 3.0
        wizard2.action_confirm()

        self.assertEqual(len(opname.line_ids), 1)
        self.assertEqual(opname.line_ids[0].quantity, 5.0, "Quantity should be additively accumulated (2 + 3 = 5).")

    def test_05_sold_qty_computation_after_date(self):
        """Test sold_qty computes sales made on or after session Date"""
        session_time = datetime.now()
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
            'date': session_time,
        })

        # Create stock move BEFORE session date (should NOT count towards sold_qty)
        move_before = self.env['stock.move'].create({
            'name': 'Sale Move Before',
            'product_id': self.product_a.id,
            'product_uom_qty': 10.0,
            'product_uom': self.product_a.uom_id.id,
            'location_id': self.location.id,
            'location_dest_id': self.customer_location.id,
            'state': 'done',
            'date': session_time - timedelta(hours=2),
        })

        # Create stock move AFTER session date (SHOULD count towards sold_qty)
        move_after = self.env['stock.move'].create({
            'name': 'Sale Move After',
            'product_id': self.product_a.id,
            'product_uom_qty': 2.0,
            'product_uom': self.product_a.uom_id.id,
            'location_id': self.location.id,
            'location_dest_id': self.customer_location.id,
            'state': 'done',
            'date': session_time + timedelta(minutes=5),
        })

        # Scan product A
        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        line = opname.line_ids[0]
        self.assertEqual(line.sold_qty, 2.0, "sold_qty should be 2.0 (only counting sales made >= session Date).")

    def test_06_action_open_camera_scanner(self):
        """Test action_open_camera_scanner returns client action dictionary"""
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
        })
        action = opname.action_open_camera_scanner()
        self.assertEqual(action.get('type'), 'ir.actions.client')
        self.assertEqual(action.get('tag'), 'realtime_stock_opname_camera_scan')

    def test_07_apply_adjustment(self):
        """Test applying the opname changes stock quant correctly using total_qty (Stock Qty - Sold Qty)"""
        session_time = datetime.now()
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
            'date': session_time,
        })

        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        line = opname.line_ids[0]
        line.quantity = 42.0

        # Create stock move AFTER session date (sold_qty = 2.0)
        self.env['stock.move'].create({
            'name': 'Sale Move For Apply Adjustment',
            'product_id': self.product_a.id,
            'product_uom_qty': 2.0,
            'product_uom': self.product_a.uom_id.id,
            'location_id': self.location.id,
            'location_dest_id': self.customer_location.id,
            'state': 'done',
            'date': session_time + timedelta(minutes=1),
        })

        self.assertEqual(line.sold_qty, 2.0)
        self.assertEqual(line.total_qty, 40.0)

        opname.action_apply()
        self.assertEqual(opname.state, 'done', "The stock opname state should be done.")

        # Check stock quant (should be total_qty = 40.0)
        quant = self.env['stock.quant'].search([
            ('product_id', '=', self.product_a.id),
            ('location_id', '=', self.location.id),
            ('lot_id', '=', False),
            ('package_id', '=', False),
            ('owner_id', '=', False)
        ], limit=1)
        self.assertTrue(quant, "A stock quant should exist after applying adjustment.")
        self.assertEqual(quant.quantity, 40.0, "Quantity in stock quant should equal total_qty (40.0).")

    def test_08_unlock_action(self):
        """Test unlock button resets state from done to draft"""
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
        })
        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()
        opname.action_apply()
        self.assertEqual(opname.state, 'done')

        opname.action_unlock()
        self.assertEqual(opname.state, 'draft', "The stock opname state should be unlocked back to draft.")

    def test_09_dynamic_sold_qty_update_realtime(self):
        """Test sold_qty computes dynamically without requiring store or re-save when new stock move occurs"""
        session_time = datetime.now()
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
            'date': session_time,
        })
        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        line = opname.line_ids[0]
        self.assertEqual(line.sold_qty, 0.0)

        # Create stock move AFTER line creation
        self.env['stock.move'].create({
            'name': 'Realtime Sale Move',
            'product_id': self.product_a.id,
            'product_uom_qty': 5.0,
            'product_uom': self.product_a.uom_id.id,
            'location_id': self.location.id,
            'location_dest_id': self.customer_location.id,
            'state': 'done',
            'date': session_time + timedelta(minutes=1),
        })

        # Re-evaluating line.sold_qty should dynamically return 5.0
        self.assertEqual(line.sold_qty, 5.0, "sold_qty should dynamically reflect new sales in real time.")

    def test_10_total_qty_computation(self):
        """Test total_qty computes Stock Qty (quantity) - Sold Qty (sold_qty)"""
        session_time = datetime.now()
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
            'date': session_time,
        })
        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        line = opname.line_ids[0]
        line.quantity = 10.0

        # Create stock move AFTER session date
        self.env['stock.move'].create({
            'name': 'Sale Move For Total Qty',
            'product_id': self.product_a.id,
            'product_uom_qty': 3.0,
            'product_uom': self.product_a.uom_id.id,
            'location_id': self.location.id,
            'location_dest_id': self.customer_location.id,
            'state': 'done',
            'date': session_time + timedelta(minutes=1),
        })

        self.assertEqual(line.quantity, 10.0)
        self.assertEqual(line.sold_qty, 3.0)
        self.assertEqual(line.total_qty, 7.0, "total_qty should equal Stock Qty (10.0) - Sold Qty (3.0) = 7.0")

    def test_11_stocktaking_list_fields(self):
        """Test fields on stocktaking list related from product and session"""
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
        })
        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        self.assertEqual(opname.user_id, self.env.user, "default user_id on realtime.stock.opname should be current user")
        line = opname.line_ids[0]
        self.assertEqual(line.categ_id, self.product_a.categ_id)
        self.assertEqual(line.location_id, self.location, "location_id on line should match opname location_id")
        self.assertEqual(line.cost_price, self.product_a.standard_price)
        self.assertEqual(line.lst_price, self.product_a.lst_price)
        self.assertEqual(line.reference, opname.name)
        self.assertEqual(line.date, opname.date)
        self.assertEqual(line.user_id, opname.user_id, "user_id on line should match opname user_id")
        self.assertEqual(line.total_cost, line.quantity * line.cost_price, "total_cost should equal quantity * cost_price")
        self.assertEqual(line.total_sales_price, line.quantity * line.lst_price, "total_sales_price should equal quantity * lst_price")

        # Check action stocktaking list
        action = self.env.ref('realtime_stock_opname.action_stocktaking_list')
        self.assertEqual(action.res_model, 'realtime.stock.opname.line')
        self.assertEqual(action.context, "{'search_default_group_location': 1}")

    def test_12_location_filter_setting(self):
        """Test Filter By Locations setting restricts location_id domain"""
        # Create a second internal location
        loc2 = self.env['stock.location'].create({
            'name': 'Test Internal Location 2',
            'usage': 'internal',
        })

        # By default (no setting), _get_location_domain allows both internal locations
        domain_default = self.env['realtime.stock.opname']._get_location_domain()
        self.assertEqual(domain_default, [('usage', '=', 'internal')])

        # Set Filter By Locations, Allowed Apply Adjustment Users, and Allowed Document Lock Users in settings wizard
        config = self.env['res.config.settings'].create({
            'stock_opname_location_ids': [(6, 0, [self.location.id])],
            'stock_opname_apply_user_ids': [(6, 0, [self.env.user.id])],
            'stock_opname_lock_user_ids': [(6, 0, [self.env.user.id])],
        })
        config.set_values()

        # Check group sync for Apply Adjustment access and Document Lock access
        group_apply = self.env.ref('realtime_stock_opname.group_realtime_stock_opname_apply')
        self.assertIn(self.env.user, group_apply.users)
        group_lock = self.env.ref('realtime_stock_opname.group_realtime_stock_opname_lock')
        self.assertIn(self.env.user, group_lock.users)

        # Re-check domain
        domain_filtered = self.env['realtime.stock.opname']._get_location_domain()
        self.assertEqual(domain_filtered, [('usage', '=', 'internal'), ('id', 'in', [self.location.id])])

        # Test get_values loads location_ids
        config_values = self.env['res.config.settings'].get_values()
        self.assertIn('stock_opname_location_ids', config_values)
        self.assertEqual(config_values['stock_opname_location_ids'], [(6, 0, [self.location.id])])

    def test_13_draft_session_conflict(self):
        """Test draft product conflict raises UserError when scanning duplicate product across draft sessions"""
        opname1 = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
        })
        opname1.barcode_scan = '1234567890'
        opname1._onchange_barcode_scan()

        # Create second opname session at same location
        opname2 = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
        })

        # Scanning product_a in opname2 should trigger UserError / warning
        with self.assertRaises(UserError):
            opname2.process_scanned_barcode('1234567890')

        # Check _onchange_barcode_scan returns warning dictionary
        opname2.barcode_scan = '1234567890'
        result = opname2._onchange_barcode_scan()
        self.assertIn('warning', result)

    def test_14_stock_opname_division(self):
        """Test creating and managing stock opname division and assigning to session"""
        division = self.env['stock.opname.division'].create({
            'name': 'FOOD',
        })
        self.assertTrue(division.id)
        self.assertEqual(division.name, 'FOOD')

        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
            'division_id': division.id,
        })
        self.assertEqual(opname.division_id, division)

        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        line = opname.line_ids[0]
        self.assertEqual(line.division_id, division, "line.division_id should equal opname.division_id")

        action = self.env.ref('realtime_stock_opname.action_stock_opname_division')
        self.assertEqual(action.res_model, 'stock.opname.division')

    def test_15_discrepancy_reporting_computations(self):
        """Test difference_qty, discrepancy_category, and compliance_status computations"""
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
        })
        # Scan Product A (Current Qty = 0.0, Stock Qty = 1.0 -> diff = +1.0)
        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()
        line_a = opname.line_ids[0]
        self.assertEqual(line_a.difference_qty, 1.0)
        self.assertEqual(line_a.discrepancy_category, 'greater_1')
        self.assertEqual(line_a.compliance_status, 'non_compliant')

        # Check sp_x_stock_qty calculation (lst_price * quantity)
        self.assertEqual(line_a.sp_x_stock_qty, self.product_a.lst_price * 1.0)

        # Set Stock Qty = 0.0 (Current Qty = 0.0 -> diff = 0.0)
        line_a.quantity = 0.0
        self.assertEqual(line_a.difference_qty, 0.0)
        self.assertEqual(line_a.discrepancy_category, 'equal_0')
        self.assertEqual(line_a.compliance_status, 'compliant')
        self.assertEqual(line_a.sp_x_stock_qty, 0.0)

        # Set Current Qty = 5.0, Stock Qty = 2.0 -> diff = -3.0
        line_a.current_qty = 5.0
        line_a.quantity = 2.0
        self.assertEqual(line_a.difference_qty, -3.0)
        self.assertEqual(line_a.discrepancy_category, 'less_minus_1')
        self.assertEqual(line_a.compliance_status, 'non_compliant')
        self.assertEqual(line_a.sp_x_stock_qty, self.product_a.lst_price * 2.0)

        # Set Current Qty = -3.0, Stock Qty = 2.0 -> diff = -3.0 + 2.0 = -1.0
        line_a.current_qty = -3.0
        line_a.quantity = 2.0
        self.assertEqual(line_a.difference_qty, -1.0)
        self.assertEqual(line_a.discrepancy_category, 'less_minus_1')
        self.assertEqual(line_a.compliance_status, 'non_compliant')

        action = self.env.ref('realtime_stock_opname.action_report_stock_discrepancies')
        self.assertEqual(action.res_model, 'realtime.stock.opname.line')

    def test_16_products_not_recorded_action(self):
        """Test action_open_products_not_recorded returns stock.quant window action with custom form view and location groupby"""
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
        })
        # Scan Product A only
        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        action = self.env['realtime.stock.opname.line'].action_open_products_not_recorded()
        self.assertEqual(action.get('res_model'), 'stock.quant')
        self.assertEqual(action.get('context', {}).get('search_default_groupby_location'), 1)
        form_view_id = self.env.ref('realtime_stock_opname.view_product_not_recorded_form').id
        self.assertIn((form_view_id, 'form'), action.get('views', []))

        # Check stock.quant barcode and categ_id fields
        quant = self.env['stock.quant'].create({
            'product_id': self.product_a.id,
            'location_id': self.location.id,
            'quantity': 10.0,
        })
        self.assertEqual(quant.barcode, self.product_a.barcode)
        self.assertEqual(quant.categ_id, self.product_a.categ_id)

    def test_17_internal_transfer_qty_computation(self):
        """Test internal_transfer_qty computes net internal transfers completed after session date and deducts from total_qty"""
        session_time = datetime.now()
        internal_loc_dest = self.env['stock.location'].create({
            'name': 'Test Internal Loc Dest',
            'usage': 'internal',
        })

        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
            'date': session_time,
        })

        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        line = opname.line_ids[0]
        line.quantity = 300.0

        self.assertEqual(line.internal_transfer_qty, 0.0)
        self.assertEqual(line.total_qty, 300.0)

        # Create internal transfer move OUT (20 units) completed after session date
        self.env['stock.move'].create({
            'name': 'Internal Move Out',
            'product_id': self.product_a.id,
            'product_uom_qty': 20.0,
            'product_uom': self.product_a.uom_id.id,
            'location_id': self.location.id,
            'location_dest_id': internal_loc_dest.id,
            'state': 'done',
            'date': session_time + timedelta(minutes=5),
        })

        self.assertEqual(line.internal_transfer_qty, 20.0, "internal_transfer_qty should be 20.0 for outgoing internal transfer.")
        self.assertEqual(line.total_qty, 280.0, "total_qty should equal 300.0 - 0.0 - 20.0 = 280.0.")

        # Create internal transfer move IN (5 units) completed after session date
        self.env['stock.move'].create({
            'name': 'Internal Move In',
            'product_id': self.product_a.id,
            'product_uom_qty': 5.0,
            'product_uom': self.product_a.uom_id.id,
            'location_id': internal_loc_dest.id,
            'location_dest_id': self.location.id,
            'state': 'done',
            'date': session_time + timedelta(minutes=10),
        })

        self.assertEqual(line.internal_transfer_qty, 15.0, "net internal_transfer_qty should be 20.0 - 5.0 = 15.0.")
        self.assertEqual(line.total_qty, 285.0, "total_qty should equal 300.0 - 0.0 - 15.0 = 285.0.")

    def test_18_lock_berkas_action(self):
        """Test action_lock sets state from draft to done"""
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
        })
        self.assertEqual(opname.state, 'draft')
        opname.action_lock()
        self.assertEqual(opname.state, 'done', "action_lock should set state to done")

    def test_19_stock_reconciliation_wizard_quantity_in(self):
        """Test Stock Reconciliation wizard calculates Quantity In and includes products from CGM even if not in Opname"""
        today = datetime.now().date()
        opname = self.env['realtime.stock.opname'].create({
            'location_id': self.location.id,
            'date': datetime.now(),
        })
        # Scan Product A only in opname
        opname.barcode_scan = '1234567890'
        opname._onchange_barcode_scan()

        # Create Central Goods Monitoring record containing Product B (not scanned in opname)
        if 'central.goods.monitoring' in self.env:
            cgm = self.env['central.goods.monitoring'].create({
                'name': 'GOB/TEST/001',
                'request_date': today,
                'state': 'done',
                'line_ids': [
                    (0, 0, {
                        'product_name': self.product_a.name,
                        'barcode': self.product_a.barcode,
                        'quantity_out': 10.0,
                        'quantity_in': 8.0,
                    }),
                    (0, 0, {
                        'product_name': self.product_b.name,
                        'barcode': self.product_b.barcode,
                        'quantity_out': 5.0,
                        'quantity_in': 5.0,
                    })
                ]
            })

        wizard = self.env['stock.reconciliation.wizard'].create({
            'start_date': today,
            'end_date': today,
        })

        # Test _get_cgm_product_ids includes product_b
        if 'central.goods.monitoring' in self.env:
            cgm_pids = wizard._get_cgm_product_ids(datetime.combine(today, datetime.min.time()), datetime.combine(today, datetime.max.time()))
            self.assertIn(self.product_b.id, cgm_pids, "Product B from CGM should be included in CGM product IDs")

        # Test _get_initial_qty_map
        initial_map = wizard._get_initial_qty_map([self.product_a.id, self.product_b.id], datetime.combine(today, datetime.min.time()))
        self.assertIn(self.product_a.id, initial_map)
        self.assertIn(self.product_b.id, initial_map)

        action = wizard.action_print_excel()
        self.assertEqual(action.get('type'), 'ir.actions.act_url')
        self.assertTrue(wizard.data_file, "data_file should be populated in wizard")
        self.assertTrue(wizard.filename.endswith('.xlsx'), "filename should end with .xlsx")
