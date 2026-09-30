# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name': 'Realtime Stock Opname',
    'version': '15.0.1.0.0',
    'summary': 'Fungsi untuk melakukan perubahan stock data dengan cepat menggunakan scan barcode',
    'description': """
Realtime Stock Opname
=====================
Modul ini memungkinkan user untuk melakukan stock opname (penyesuaian stok) secara cepat.
User dapat memasukkan barcode, scan barcode hardware, atau menggunakan Kamera Smartphone secara otomatis untuk memunculkan:
- Nama Produk (Product Name)
- Barcode
- Satuan (Unit of Measure)
Dan menyediakan kolom Quantity untuk mengisi jumlah data stok pada produk tersebut.
    """,
    'author': 'Jules',
    'category': 'Inventory/Inventory',
    'depends': ['stock', 'web'],
    'data': [
        'security/stock_opname_security.xml',
        'security/ir.model.access.csv',
        'views/stock_opname_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'realtime_stock_opname/static/src/js/quagga.min.js',
            'realtime_stock_opname/static/src/js/barcode_camera_scanner.js',
            'realtime_stock_opname/static/src/js/barcode_autofocus.js',
            'realtime_stock_opname/static/src/xml/camera_scanner_templates.xml',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
