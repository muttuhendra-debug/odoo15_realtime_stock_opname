{
    'name': 'Central Goods Monitoring',
    'version': '1.1',
    'category': 'Inventory',
    'summary': 'Monitor goods out requests from a remote server.',
    'description': """
        This module allows Computer B to monitor goods out requests from Computer A.
        It uses XML-RPC to connect and fetch data.
    """,
    'author': 'Jules',
    'depends': ['base', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/central_goods_monitoring_views.xml',
        'views/res_config_settings_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
