from odoo import api, fields, models, _


class ContractReportWizard(models.TransientModel):
    _name = 'contract.report.wizard'
    _description = 'Contract Retention & Advance Report Wizard'

    partner_id = fields.Many2one('res.partner', string="Customer")
    date_to = fields.Date(string="As at Date", required=True, default=fields.Date.context_today)

    def action_print_report(self):
        self.ensure_one()
        domain = [('is_contract_invoice', '=', True), ('state', '=', 'posted')]
        if self.partner_id:
            domain.append(('partner_id', '=', self.partner_id.id))

        invoices = self.env['account.move'].search(domain)
        # In Odoo, you can return a QWeb report or custom action dataset
        return self.env.ref('contract_retention_advance.action_contract_report_pdf').report_action(invoices)