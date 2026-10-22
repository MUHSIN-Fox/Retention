from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RetentionReleaseWizard(models.TransientModel):
    _name = 'retention.release.wizard'
    _description = 'Release Retention Wizard'

    invoice_id = fields.Many2one('account.move', string="Source Invoice",
                                 domain="[('is_contract_invoice', '=', True), ('state', '=', 'posted')]")
    partner_id = fields.Many2one('res.partner', string="Customer", required=True)
    project_name = fields.Char(string="Project / Contract")

    company_id = fields.Many2one('res.company', string="Company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        compute='_compute_currency_id',
        store=True,
        readonly=True
    )

    release_amount = fields.Monetary(string="Amount to Release", required=True, currency_field='currency_id')
    release_date = fields.Date(string="Release Date", required=True, default=fields.Date.context_today)

    journal_id = fields.Many2one(
        'account.journal',
        string="Journal",
        required=True,
        default=lambda self: self.env['account.journal'].search(
            [('type', '=', 'general'), ('company_id', '=', self.env.company.id)], limit=1)
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        # If opened from a specific invoice context
        if self.env.context.get('active_model') == 'account.move' and self.env.context.get('active_id'):
            invoice = self.env['account.move'].browse(self.env.context.get('active_id'))
            if invoice.is_contract_invoice:
                res.update({
                    'invoice_id': invoice.id,
                    'partner_id': invoice.partner_id.id,
                    'project_name': invoice.project_name,
                    'release_amount': invoice.retention_amount,
                })
        return res

    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        if self.invoice_id:
            self.partner_id = self.invoice_id.partner_id
            self.project_name = self.invoice_id.project_name
            self.release_amount = self.invoice_id.retention_amount

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id and not self.invoice_id:
            # Fetch the most recent project name for this customer
            last_invoice = self.env['account.move'].search([
                ('partner_id', '=', self.partner_id.id),
                ('is_contract_invoice', '=', True),
                ('project_name', '!=', False)
            ], order='invoice_date desc, id desc', limit=1)

            if last_invoice and last_invoice.project_name:
                self.project_name = last_invoice.project_name

    @api.depends('journal_id', 'company_id')
    def _compute_currency_id(self):
        for wizard in self:
            wizard.currency_id = wizard.journal_id.currency_id or wizard.company_id.currency_id or wizard.env.company.currency_id

    def action_release_retention(self):
        self.ensure_one()
        company = self.company_id
        ret_acc = company.contract_retention_account_id
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
                    'name': _("Retention Released - %s") % (self.project_name or ''),
                    'account_id': normal_acc.id,
                    'partner_id': self.partner_id.id,
                    'debit': self.release_amount,
                    'credit': 0.0,
                    'currency_id': self.currency_id.id,
                }),
                # Credit Retention Receivable (Clears retention hold)
                (0, 0, {
                    'name': _("Retention Release Clearing - %s") % (self.project_name or ''),
                    'account_id': ret_acc.id,
                    'partner_id': self.partner_id.id,
                    'debit': 0.0,
                    'credit': self.release_amount,
                    'currency_id': self.currency_id.id,
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