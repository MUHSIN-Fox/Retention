from odoo import api, fields, models, _
from odoo.exceptions import UserError

class RetentionReleaseWizard(models.TransientModel):
    _name = 'retention.release.wizard'
    _description = 'Release Retention Wizard'

    partner_id = fields.Many2one('res.partner', string="Customer", required=True)
    project_name = fields.Char(string="Project / Contract")
    retention_account_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company)
    release_amount = fields.Monetary(string="Amount to Release", required=True)
    release_date = fields.Date(string="Release Date", required=True, default=fields.Date.context_today)
    journal_id = fields.Many2one('account.journal', string="Journal", required=True, default=lambda self: self.env['account.journal'].search([('type', '=', 'general'), ('company_id', '=', self.env.company.id)], limit=1))
    currency_id = fields.Many2one('res.company', related='journal_id.currency_id')

    def action_release_retention(self):
        self.ensure_one()
        company = self.env.company
        ret_acc = company.default_retention_account_id
        normal_acc = self.partner_id.property_account_receivable_id

        if not ret_acc:
            raise UserError(_("Default Retention Receivable account is not configured in settings."))

        if self.release_amount <= 0:
            raise UserError(_("Release amount must be greater than zero."))

        # Create Journal Entry moving amount from Retention Receivable to Normal Receivable
        move_vals = {
            'journal_id': self.journal_id.id,
            'date': self.release_date,
            'ref': _("Retention Release for %s") % (self.project_name or self.partner_id.name),
            'line_ids': [
                # Debit Normal Receivable (Client owes standard due amount now)
                (0, 0, {
                    'name': _("Retention Released"),
                    'account_id': normal_acc.id,
                    'partner_id': self.partner_id.id,
                    'debit': self.release_amount,
                    'credit': 0.0,
                }),
                # Credit Retention Receivable (Clears retention hold)
                (0, 0, {
                    'name': _("Retention Released - Clearing"),
                    'account_id': ret_acc.id,
                    'partner_id': self.partner_id.id,
                    'debit': 0.0,
                    'credit': self.release_amount,
                }),
            ]
        }
        move = self.env['account.move'].create(move_vals)
        move.action_post()

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': move.id,
            'view_mode': 'form',
            'target': 'current',
        }