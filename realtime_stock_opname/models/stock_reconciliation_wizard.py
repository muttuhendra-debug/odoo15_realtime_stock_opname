# -*- coding: utf-8 -*-
import io
import base64
import xlsxwriter
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, time

class StockReconciliationWizard(models.TransientModel):
    _name = 'stock.reconciliation.wizard'
    _description = 'Stock Reconciliation Wizard'

    start_date = fields.Date(string='Start Date', required=True, default=fields.Date.context_today)
    end_date = fields.Date(string='End Date', required=True, default=fields.Date.context_today)
    data_file = fields.Binary(string='File', readonly=True)
    filename = fields.Char(string='Filename', readonly=True)

    def _get_initial_qty_map(self, product_ids, start_dt):
        if not product_ids:
            return {}

        cr = self.env.cr
        pids = tuple(product_ids)
        initial_map = {pid: 0.0 for pid in product_ids}

        # Current stock quantity on hand at internal locations
        cr.execute("""
            SELECT product_id, SUM(quantity)
            FROM stock_quant
            WHERE product_id IN %s
              AND location_id IN (SELECT id FROM stock_location WHERE usage = 'internal')
            GROUP BY product_id
        """, (pids,))
        for pid, qty in cr.fetchall():
            if pid in initial_map:
                initial_map[pid] = qty or 0.0

        # Subtract completed moves IN to internal locations occurring >= start_dt
        cr.execute("""
            SELECT sm.product_id, SUM(sm.product_uom_qty)
            FROM stock_move sm
            JOIN stock_location dest_loc ON dest_loc.id = sm.location_dest_id
            WHERE sm.product_id IN %s
              AND dest_loc.usage = 'internal'
              AND sm.state = 'done'
              AND sm.date >= %s
            GROUP BY sm.product_id
        """, (pids, start_dt))
        for pid, qty in cr.fetchall():
            if pid in initial_map:
                initial_map[pid] -= (qty or 0.0)

        # Add completed moves OUT from internal locations occurring >= start_dt
        cr.execute("""
            SELECT sm.product_id, SUM(sm.product_uom_qty)
            FROM stock_move sm
            JOIN stock_location src_loc ON src_loc.id = sm.location_id
            WHERE sm.product_id IN %s
              AND src_loc.usage = 'internal'
              AND sm.state = 'done'
              AND sm.date >= %s
            GROUP BY sm.product_id
        """, (pids, start_dt))
        for pid, qty in cr.fetchall():
            if pid in initial_map:
                initial_map[pid] += (qty or 0.0)

        return initial_map

    def _get_sold_qty_map(self, product_ids, start_dt, end_dt):
        if not product_ids:
            return {}

        cr = self.env.cr
        sold_map = {pid: 0.0 for pid in product_ids}

        cr.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name = 'pos_order'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name = 'pos_order_line'
            )
        """)
        has_pos = cr.fetchone()[0]

        pos_counted_move_ids = set()

        if has_pos:
            query_pos = """
                SELECT pol.product_id, SUM(pol.qty)
                FROM pos_order_line pol
                JOIN pos_order po ON po.id = pol.order_id
                WHERE pol.product_id IN %s
                  AND po.date_order >= %s
                  AND po.date_order <= %s
                  AND po.state IN ('draft', 'paid', 'done', 'invoiced')
                GROUP BY pol.product_id
            """
            cr.execute(query_pos, (tuple(product_ids), start_dt, end_dt))
            for pid, qty_sum in cr.fetchall():
                if pid in sold_map:
                    sold_map[pid] += (qty_sum or 0.0)

            cr.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.columns WHERE table_name='pos_order' AND column_name='picking_id'
                )
            """)
            has_pos_picking = cr.fetchone()[0]
            if has_pos_picking:
                query_moves = """
                    SELECT sm.id
                    FROM stock_move sm
                    JOIN pos_order po ON po.picking_id = sm.picking_id
                    WHERE sm.product_id IN %s
                      AND po.date_order >= %s
                      AND po.date_order <= %s
                      AND po.state IN ('draft', 'paid', 'done', 'invoiced')
                """
                cr.execute(query_moves, (tuple(product_ids), start_dt, end_dt))
                for (m_id,) in cr.fetchall():
                    pos_counted_move_ids.add(m_id)

        where_moves = [
            "sm.product_id IN %s",
            "dest_loc.usage = 'customer'",
            "sm.state = 'done'",
            "sm.date >= %s",
            "sm.date <= %s"
        ]
        params_stock = [tuple(product_ids), start_dt, end_dt]

        if pos_counted_move_ids:
            where_moves.append("sm.id NOT IN %s")
            params_stock.append(tuple(pos_counted_move_ids))

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
            if pid in sold_map:
                sold_map[pid] += (qty_sum or 0.0)

        return sold_map

    def _get_sold_capital_map(self, product_ids, start_dt, end_dt, sold_qty_map):
        if not product_ids:
            return {}

        cr = self.env.cr
        capital_map = {pid: 0.0 for pid in product_ids}
        val_qty_map = {pid: 0.0 for pid in product_ids}

        cr.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name = 'stock_valuation_layer'
            )
        """)
        has_svl = cr.fetchone()[0]

        if has_svl:
            query_svl = """
                SELECT svl.product_id, SUM(ABS(svl.value)), SUM(ABS(svl.quantity))
                FROM stock_valuation_layer svl
                JOIN stock_move sm ON sm.id = svl.stock_move_id
                JOIN stock_location dest_loc ON dest_loc.id = sm.location_dest_id
                WHERE svl.product_id IN %s
                  AND sm.state = 'done'
                  AND dest_loc.usage = 'customer'
                  AND sm.date >= %s
                  AND sm.date <= %s
                  AND svl.quantity < 0
                GROUP BY svl.product_id
            """
            cr.execute(query_svl, (tuple(product_ids), start_dt, end_dt))
            for pid, val_sum, qty_sum in cr.fetchall():
                if pid in capital_map:
                    capital_map[pid] += (val_sum or 0.0)
                    val_qty_map[pid] += (qty_sum or 0.0)

        products = self.env['product.product'].browse(product_ids)
        for product in products:
            pid = product.id
            total_sold = sold_qty_map.get(pid, 0.0)
            covered_qty = val_qty_map.get(pid, 0.0)
            uncovered_qty = max(0.0, total_sold - covered_qty)
            if uncovered_qty > 0:
                capital_map[pid] += uncovered_qty * (product.standard_price or 0.0)

        return capital_map

    def _get_quantity_in_map(self, product_ids, start_dt, end_dt):
        if not product_ids:
            return {}

        qty_in_map = {pid: 0.0 for pid in product_ids}

        cr = self.env.cr
        cr.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name = 'central_goods_monitoring'
            ) AND EXISTS (
                SELECT 1 FROM information_schema.tables WHERE table_name = 'central_goods_monitoring_line'
            )
        """)
        has_central = cr.fetchone()[0]

        if not has_central:
            return qty_in_map

        import re
        products = self.env['product.product'].browse(product_ids)
        barcode_to_pid = {}
        name_to_pid = {}

        for product in products:
            if product.barcode:
                barcode_to_pid[product.barcode.strip()] = product.id
            if product.name:
                name_to_pid[product.name.strip()] = product.id
            if product.display_name:
                name_to_pid[product.display_name.strip()] = product.id
                clean_display = re.sub(r'^\[.*?\]\s*', '', product.display_name).strip()
                if clean_display:
                    name_to_pid[clean_display] = product.id

        start_date = start_dt.date()
        end_date = end_dt.date()

        query = """
            SELECT cgml.barcode, cgml.product_name, SUM(cgml.quantity_in)
            FROM central_goods_monitoring_line cgml
            JOIN central_goods_monitoring cgm ON cgm.id = cgml.monitoring_id
            WHERE (
                (cgm.request_date >= %s AND cgm.request_date <= %s)
                OR (cgm.request_date IS NULL AND cgm.create_date >= %s AND cgm.create_date <= %s)
            )
            GROUP BY cgml.barcode, cgml.product_name
        """
        cr.execute(query, (start_date, end_date, start_dt, end_dt))

        for barcode, product_name, qty_sum in cr.fetchall():
            pid = None
            clean_pname = re.sub(r'^\[.*?\]\s*', '', product_name.strip()).strip() if product_name else ''
            if barcode and barcode.strip() in barcode_to_pid:
                pid = barcode_to_pid[barcode.strip()]
            elif product_name and product_name.strip() in name_to_pid:
                pid = name_to_pid[product_name.strip()]
            elif clean_pname and clean_pname in name_to_pid:
                pid = name_to_pid[clean_pname]

            if pid and pid in qty_in_map:
                qty_in_map[pid] += (qty_sum or 0.0)

        return qty_in_map

    def _get_reconciliation_data(self):
        if self.start_date > self.end_date:
            raise UserError(_("Start Date cannot be greater than End Date."))

        start_dt = datetime.combine(self.start_date, time.min)
        end_dt = datetime.combine(self.end_date, time.max)

        all_products = self.env['product.product'].search([])
        all_product_ids = set(all_products.ids)

        initial_qty_map = self._get_initial_qty_map(all_product_ids, start_dt)
        sold_qty_map = self._get_sold_qty_map(all_product_ids, start_dt, end_dt)
        sold_capital_map = self._get_sold_capital_map(all_product_ids, start_dt, end_dt, sold_qty_map)
        quantity_in_map = self._get_quantity_in_map(all_product_ids, start_dt, end_dt)

        import re
        data = []
        products = self.env['product.product'].browse(list(all_product_ids))
        for product in products:
            product_name = product.name or product.display_name
            if product_name:
                product_name = re.sub(r'^\[.*?\]\s*', '', product_name).strip()

            barcode = product.barcode or ''
            categ_id = product.categ_id.id if product.categ_id else False
            initial_qty = initial_qty_map.get(product.id, 0.0)
            sold_qty = sold_qty_map.get(product.id, 0.0)
            quantity_in = quantity_in_map.get(product.id, 0.0)
            ending_qty = initial_qty + quantity_in - sold_qty
            total_capital = sold_capital_map.get(product.id, 0.0)
            total_sales = sold_qty * (product.lst_price or 0.0)
            total_cost_incoming = quantity_in * (product.standard_price or 0.0)
            total_sales_incoming = quantity_in * (product.lst_price or 0.0)

            data.append({
                'product_id': product.id,
                'product_name': product_name,
                'barcode': barcode,
                'categ_id': categ_id,
                'initial_qty': initial_qty,
                'ending_qty': ending_qty,
                'sold_qty': sold_qty,
                'quantity_in': quantity_in,
                'total_cost': total_capital,
                'total_sales': total_sales,
                'total_cost_incoming': total_cost_incoming,
                'total_sales_incoming': total_sales_incoming,
                'user_id': self.env.uid,
            })

        return data

    def action_fetch_data(self):
        self.ensure_one()
        records_data = self._get_reconciliation_data()

        LineModel = self.env['stock.reconciliation.line']
        LineModel.search([('user_id', '=', self.env.uid)]).unlink()

        LineModel.create(records_data)

        action = self.env["ir.actions.actions"]._for_xml_id("realtime_stock_opname.action_stock_reconciliation_line")
        return action

    def action_print_excel(self):
        self.ensure_one()
        data = self._get_reconciliation_data()

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Stock Reconciliation')

        # Formats
        header_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'bg_color': '#D3D3D3',
            'border': 1
        })
        cell_format = workbook.add_format({'border': 1})
        num_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})

        headers = ['Product', 'Barcode', 'Product Category', 'Initial Qty', 'Ending Qty', 'Sold Qty', 'Quantity In', 'Total Cost', 'Total Sales', 'Total Cost Of Incoming Goods', 'Total Sales Of Incoming Goods']
        for col_num, header in enumerate(headers):
            worksheet.write(0, col_num, header, header_format)
            worksheet.set_column(col_num, col_num, 20)

        row_num = 1
        for row in data:
            categ = self.env['product.category'].browse(row['categ_id']) if row['categ_id'] else False
            category_name = categ.complete_name or categ.name if categ else ''

            worksheet.write(row_num, 0, row['product_name'], cell_format)
            worksheet.write(row_num, 1, row['barcode'], cell_format)
            worksheet.write(row_num, 2, category_name, cell_format)
            worksheet.write(row_num, 3, row['initial_qty'], num_format)
            worksheet.write(row_num, 4, row['ending_qty'], num_format)
            worksheet.write(row_num, 5, row['sold_qty'], num_format)
            worksheet.write(row_num, 6, row['quantity_in'], num_format)
            worksheet.write(row_num, 7, row['total_cost'], num_format)
            worksheet.write(row_num, 8, row['total_sales'], num_format)
            worksheet.write(row_num, 9, row['total_cost_incoming'], num_format)
            worksheet.write(row_num, 10, row['total_sales_incoming'], num_format)
            row_num += 1

        workbook.close()
        output.seek(0)
        file_data = base64.b64encode(output.read())
        output.close()

        file_name = f"Stock_Reconciliation_{self.start_date}_to_{self.end_date}.xlsx"
        self.write({
            'data_file': file_data,
            'filename': file_name
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/?model=stock.reconciliation.wizard&id={self.id}&field=data_file&filename_field=filename&download=true&filename={file_name}',
            'target': 'self',
        }
