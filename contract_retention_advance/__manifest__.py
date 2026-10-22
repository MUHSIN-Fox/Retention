{
    'name': 'Contracting Retention and Advance Management',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Manage customer retentions, advance recoveries, and project-wise tracking for contracting companies.',
    'description': """
        Features:
        - Configurable Default Retention Account & Percentage.
        - Invoice-level Retention % and Advance Payment matching (Percentage or Fixed).
        - Split receivable journal entries: Normal Receivable vs. Retention Receivable with expected handover due dates.
        - Automatic advance recovery matching and validation against unallocated payments.
        - Retention Release wizard to move retention to normal receivables.
        - Proper Credit Note reversal proportioning.
        - Robust Draft-to-Posted idempotency.
        - Comprehensive Project & Customer Ledger Report with Excel Export.
        - Custom QWeb invoice print format.
    """,
    'author': 'MUHSIN',
    'depends': ['account', 'sale_management', 'l10n_sa','l10n_sa_edi'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/account_move_views.xml',
        'wizards/retention_release_wizard_views.xml',
        'reports/contract_report_views.xml',
        'reports/invoice_report_template.xml',
    ],
    'assets': {
        'web.report_assets_common': [
            'contract_retention_advance/static/src/css/report.css',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}