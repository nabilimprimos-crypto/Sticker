{
    'name': 'Sticker Workflow',
    'version': '16.0.1.0.0',
    'summary': 'Suivi du processus de fabrication de stickers',
    'category': 'Manufacturing',
    'author': 'Sticker Cloud ERP',
    'depends': ['base', 'mail', 'sale_management'],
    'data': [
        'security/ir.model.access.csv',
        'data/sticker_stages.xml',
        'views/sticker_order_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
