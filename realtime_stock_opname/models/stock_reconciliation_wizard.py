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

    def _get_cgm_product_ids(self, start_dt, end_dt):
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
            return set()

        import re
        start_date = start_dt.date()
        end_date = end_dt.date()

        query = """
            SELECT DISTINCT cgml.barcode, cgml.product_name
            FROM central_goods_monitoring_line cgml
            JOIN central_goods_monitoring cgm ON cgm.id = cgml.monitoring_id
            WHERE (
                (cgm.request_date >= %s AND cgm.request_date <= %s)
                OR (cgm.request_date IS NULL AND cgm.create_date >= %s AND cgm.create_date <= %s)
            )
        """
        cr.execute(query, (start_date, end_date, start_dt, end_dt))
        pairs = cr.fetchall()
        if not pairs:
            return set()

        barcodes = list(set(b.strip() for b, name in pairs if b and b.strip()))
        raw_names = list(set(name.strip() for b, name in pairs if name and name.strip()))
        clean_names = list(set(re.sub(r'^\[.*?\]\s*', '', n).strip() for n in raw_names if n))

        all_search_names = list(set(raw_names + clean_names))

        domain = []
        if barcodes and all_search_names:
            domain = ['|', ('barcode', 'in', barcodes), ('name', 'in', all_search_names)]
        elif barcodes:
            domain = [('barcode', 'in', barcodes)]
        elif all_search_names:
            domain = [('name', 'in', all_search_names)]

        matched_products = self.env['product.product'].search(domain) if domain else self.env['product.product']

        barcode_map = {p.barcode.strip(): p.id for p in matched_products if p.barcode}
        name_map = {}
        for p in matched_products:
            if p.name:
                name_map[p.name.strip()] = p.id
            if p.display_name:
                name_map[p.display_name.strip()] = p.id
                clean_disp = re.sub(r'^\[.*?\]\s*', '', p.display_name).strip()
                if clean_disp:
                    name_map[clean_disp] = p.id

        matched_pids = set()
        for barcode, product_name in pairs:
            clean_pname = re.sub(r'^\[.*?\]\s*', '', product_name.strip()).strip() if product_name else ''
            if barcode and barcode.strip() in barcode_map:
                matched_pids.add(barcode_map[barcode.strip()])
            elif product_name and product_name.strip() in name_map:
                matched_pids.add(name_map[product_name.strip()])
            elif clean_pname and clean_pname in name_map:
                matched_pids.add(name_map[clean_pname])

        return matched_pids

    def action_print_excel(self):
        self.ensure_one()
        if self.start_date > self.end_date:
            raise UserError(_("Start Date cannot be greater than End Date."))

        start_dt = datetime.combine(self.start_date, time.min)
        end_dt = datetime.combine(self.end_date, time.max)

        lines = self.env['realtime.stock.opname.line'].search([
            ('opname_id.date', '>=', start_dt),
            ('opname_id.date', '<=', end_dt)
        ])

        opname_product_ids = set(line.product_id.id for line in lines if line.product_id)
        cgm_product_ids = self._get_cgm_product_ids(start_dt, end_dt)
        all_product_ids = opname_product_ids | cgm_product_ids

        initial_qty_map = self._get_initial_qty_map(all_product_ids, start_dt)
        sold_qty_map = self._get_sold_qty_map(all_product_ids, start_dt, end_dt)
        quantity_in_map = self._get_quantity_in_map(all_product_ids, start_dt, end_dt)

        opname_line_by_product = {}
        for line in lines:
            if line.product_id:
                opname_line_by_product[line.product_id.id] = line

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

        headers = ['Product', 'Barcode', 'Current Qty', 'Stock Qty', 'Initial Qty', 'Ending Qty', 'Sold Qty', 'Quantity In', 'TOTAL CAPITAL']
        for col_num, header in enumerate(headers):
            worksheet.write(0, col_num, header, header_format)
            worksheet.set_column(col_num, col_num, 20)

        row_num = 1
        products = self.env['product.product'].browse(list(all_product_ids))
        for product in products:
            line = opname_line_by_product.get(product.id)
            if line:
                product_name = line.product_name or product.display_name
                barcode = line.barcode or product.barcode or ''
                current_qty = line.current_qty
                stock_qty = line.quantity
            else:
                product_name = product.display_name
                barcode = product.barcode or ''
                quants = self.env['stock.quant'].search([
                    ('product_id', '=', product.id),
                    ('location_id.usage', '=', 'internal')
                ])
                current_qty = sum(quants.mapped('quantity'))
                stock_qty = 0.0

            initial_qty = initial_qty_map.get(product.id, 0.0)
            sold_qty = sold_qty_map.get(product.id, 0.0)
            quantity_in = quantity_in_map.get(product.id, 0.0)
            ending_qty = initial_qty + quantity_in - sold_qty
            total_capital = sold_qty * (product.standard_price or 0.0)

            worksheet.write(row_num, 0, product_name, cell_format)
            worksheet.write(row_num, 1, barcode, cell_format)
            worksheet.write(row_num, 2, current_qty, num_format)
            worksheet.write(row_num, 3, stock_qty, num_format)
            worksheet.write(row_num, 4, initial_qty, num_format)
            worksheet.write(row_num, 5, ending_qty, num_format)
            worksheet.write(row_num, 6, sold_qty, num_format)
            worksheet.write(row_num, 7, quantity_in, num_format)
            worksheet.write(row_num, 8, total_capital, num_format)
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
