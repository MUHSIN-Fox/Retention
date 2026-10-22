from odoo import fields, models

class ResCompany(models.Model):
    _inherit = 'res.company'

    default_retention_account_id = fields.Many2one(
        'account.account',
        string="Default Retention Receivable Account",
        domain="[('account_type', '=', 'asset_receivable'), ('company_id', '=', id)]"
    )
    default_retention_percentage = fields.Float(
        string="Default Retention %",
        default=10.0
    )

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    default_retention_account_id = fields.Many2one(
        'account.account',
        related='company_id.default_retention_account_id',
        readonly=False,
        string="Default Retention Account"
    )
    default_retention_percentage = fields.Float(
        related='company_id.default_retention_percentage',
        readonly=False,
        string="Default Retention %"
    )