from odoo.tests.common import TransactionCase
from unittest.mock import patch, MagicMock

class TestCentralGoodsMonitoringSync(TransactionCase):

    def setUp(self):
        super(TestCentralGoodsMonitoringSync, self).setUp()
        self.Monitoring = self.env['central.goods.monitoring']
        self.env['ir.config_parameter'].sudo().set_param('central_goods_monitoring.remote_server_url', 'http://test-server')
        self.env['ir.config_parameter'].sudo().set_param('central_goods_monitoring.remote_server_db', 'test-db')
        self.env['ir.config_parameter'].sudo().set_param('central_goods_monitoring.remote_server_username', 'admin')
        self.env['ir.config_parameter'].sudo().set_param('central_goods_monitoring.remote_server_password', 'admin')
        self.env['ir.config_parameter'].sudo().set_param('central_goods_monitoring.destination_location_name', 'Branch A')

    @patch('xmlrpc.client.ServerProxy')
    def test_action_fetch_data(self, mock_server_proxy):
        # Mocking common.authenticate
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 1

        # Mocking models.execute_kw
        mock_models = MagicMock()
        mock_models.execute_kw.side_effect = [
            # First call for goods.out.branch
            [{
                'id': 101,
                'name': 'GOut/001',
                'responsible_id': [1, 'Admin'],
                'source_location_id': [2, 'WH/Stock'],
                'request_date': '2023-10-27',
                'destination_location_id': [3, 'Branch A'],
                'state': 'confirmed'
            }],
            # Third call (after write) for goods.out.branch.line
            [{
                'id': 201,
                'product_id': [10, 'Laptop'],
                'barcode': '123456',
                'category_id': [5, 'Electronics'],
                'uom_id': [1, 'Units'],
                'quantity_out': 5.0
            }]
        ]

        # Configure mock_server_proxy to return different mocks based on URL
        def side_effect(url):
            if 'common' in url:
                return mock_common
            return mock_models

        mock_server_proxy.side_effect = side_effect

        self.Monitoring.action_fetch_data()

        # Check if record is created
        monitoring_rec = self.Monitoring.search([('remote_id', '=', 101)])
        self.assertTrue(monitoring_rec)
        self.assertEqual(monitoring_rec.name, 'GOut/001')

        # Check lines and remote_line_id
        self.assertEqual(len(monitoring_rec.line_ids), 1)
        self.assertEqual(monitoring_rec.line_ids[0].product_name, 'Laptop')
        self.assertEqual(monitoring_rec.line_ids[0].remote_line_id, 201)

    @patch('xmlrpc.client.ServerProxy')
    def test_action_validate_with_push(self, mock_server_proxy):
        # Setup mocks for validation status push
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 1
        mock_models = MagicMock()

        def side_effect(url):
            if 'common' in url:
                return mock_common
            return mock_models
        mock_server_proxy.side_effect = side_effect

        # Create a product with matching barcode
        product = self.env['product.product'].create({
            'name': 'Laptop',
            'barcode': '123456',
            'type': 'product'
        })

        # Create a location
        location = self.env['stock.location'].create({
            'name': 'Test Branch Location',
            'usage': 'internal'
        })

        # Create a monitoring record
        monitoring = self.env['central.goods.monitoring'].create({
            'name': 'GOut/001',
            'remote_id': 101,
            'branch_stock_source_id': location.id,
            'line_ids': [(0, 0, {
                'product_name': 'Laptop',
                'barcode': '123456',
                'quantity_out': 5.0,
                'quantity_in': 4.0, # Differing quantity
                'remote_line_id': 201,
            })]
        })

        # Validate
        monitoring.action_validate()

        # Check state
        self.assertEqual(monitoring.local_state, 'validated')

        # Check if remote write was called for both header and line
        remote_writes = [call for call in mock_models.execute_kw.call_args_list if call[0][4] == 'write']

        # Header update
        header_write = [w for w in remote_writes if w[0][3] == 'goods.out.branch']
        self.assertTrue(header_write)
        self.assertEqual(header_write[0][0][5], [[101]])
        self.assertEqual(header_write[0][0][6]['branch_status'], 'Validated')

        # Line update
        line_write = [w for w in remote_writes if w[0][3] == 'goods.out.branch.line']
        self.assertTrue(line_write)
        self.assertEqual(line_write[0][0][5], [[201]])
        self.assertEqual(line_write[0][0][6]['quantity_in'], 4.0)

    def test_is_new_product_computation(self):
        # Create a local product
        self.env['product.product'].create({
            'name': 'Existing Mouse',
            'barcode': 'MOUSE123',
            'type': 'product'
        })

        monitoring = self.env['central.goods.monitoring'].create({
            'name': 'GOut/002',
            'remote_id': 102,
            'line_ids': [
                (0, 0, {
                    'product_name': 'Existing Mouse',
                    'barcode': 'MOUSE123',
                    'quantity_out': 2.0,
                }),
                (0, 0, {
                    'product_name': 'New Keyboard',
                    'barcode': 'KEYBOARD999',
                    'quantity_out': 1.0,
                })
            ]
        })

        line_existing = monitoring.line_ids.filtered(lambda l: l.barcode == 'MOUSE123')
        line_new = monitoring.line_ids.filtered(lambda l: l.barcode == 'KEYBOARD999')

        self.assertFalse(line_existing.is_new_product)
        self.assertTrue(line_new.is_new_product)

        # Search lines with domain [('is_new_product', '=', True)]
        new_lines = self.env['central.goods.monitoring.line'].search([('is_new_product', '=', True)])
        self.assertIn(line_new, new_lines)
        self.assertNotIn(line_existing, new_lines)
