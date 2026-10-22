from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class AccountMove(models.Model):
    _inherit = 'account.move'

    is_contract_invoice = fields.Boolean(string="Contract Retention Invoice", default=False)
    retention_percentage = fields.Float(string="Retention %",
                                        default=lambda self: self.env.company.default_retention_percentage)
    retention_amount = fields.Monetary(string="Retention Amount", compute='_compute_contract_amounts', store=True,
                                       readonly=False)

    advance_payment_id = fields.Many2one(
        'account.payment',
        string="Advance Payment to Recover",
        domain="[('partner_id', '=', commercial_partner_id), ('payment_type', '=', 'inbound'), ('state', '=', 'posted')]"
    )
    advance_recovery_type = fields.Selection([
        ('percentage', 'Percentage of Work Done'),
        ('fixed', 'Fixed Amount')
    ], string="Recovery Type", default='percentage')
    advance_recovery_percentage = fields.Float(string="Advance Recovery %", default=20.0)
    advance_recovery_amount = fields.Monetary(string="Advance Recovery Amount", compute='_compute_contract_amounts',
                                              store=True, readonly=False)

    retention_account_id = fields.Many2one(
        'account.account',
        string="Retention Receivable Account",
        default=lambda self: self.env.company.default_retention_account_id
    )
    handover_date = fields.Date(string="Expected Handover Date")
    project_name = fields.Char(string="Project / Sales Order", compute='_compute_project_name', store=True)

    @api.depends('invoice_line_ids', 'invoice_line_ids.price_subtotal')
    def _compute_project_name(self):
        for move in self:
            so = move.invoice_line_ids.sale_line_ids.order_id
            if so:
                move.project_name = so.name
            else:
                move.project_name = f"General - {move.partner_id.name}" if move.partner_id else "General"

    @api.depends('is_contract_invoice', 'retention_percentage', 'retention_amount', 'advance_recovery_type',
                 'advance_recovery_percentage', 'advance_recovery_amount', 'amount_untaxed')
    def _compute_contract_amounts(self):
        for move in self:
            if not move.is_contract_invoice:
                move.retention_amount = 0.0
                move.advance_recovery_amount = 0.0
                continue

            base_work_done = move.amount_untaxed  # Work done before tax

            # Retention calculation (usually % of work done)
            if move.retention_percentage:
                move.retention_amount = round(base_work_done * (move.retention_percentage / 100.0), 2)

            # Advance Recovery calculation
            if move.advance_recovery_type == 'percentage':
                move.advance_recovery_amount = round(base_work_done * (move.advance_recovery_percentage / 100.0), 2)
            else:
                # fixed amount is kept as entered by user
                pass

    @api.constrains('advance_payment_id', 'advance_recovery_amount', 'is_contract_invoice')
    def _check_advance_recovery(self):
        for move in self:
            if move.is_contract_invoice and move.advance_payment_id and move.advance_recovery_amount:
                # Check remaining advance on payment
                reconciled_amount = sum(move.advance_payment_id.matched_debit_ids.mapped('amount')) + sum(
                    move.advance_payment_id.matched_credit_ids.mapped('amount'))
                remaining_advance = move.advance_payment_id.amount - reconciled_amount
                if move.advance_recovery_amount > remaining_advance + 0.01:
                    raise ValidationError(
                        _("Advance recovery amount (%.2f) exceeds remaining advance balance (%.2f) on payment %s.") %
                        (move.advance_recovery_amount, remaining_advance, move.advance_payment_id.name))

    def _post(self, soft=True):
        res = super()._post(soft=soft)
        for move in res:
            if move.is_contract_invoice and move.move_type == 'out_invoice':
                move._process_contract_posting_splits()
        return res

    def _process_contract_posting_splits(self):
        """Adjusts journal entry lines: splits retention into retention account and matches advance recovery."""
        self.ensure_one()
        if not self.retention_amount and not self.advance_recovery_amount:
            return

        receivable_line = self.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable' and not l.tax_line_id)
        if not receivable_line:
            return

        # Disable auto-balancing temporarily to adjust lines safely
        self.env.액 = True  # internal flag or use direct SQL/line updates

        # 1. Handle Retention Split
        if self.retention_amount > 0:
            ret_acc = self.retention_account_id or self.company_id.default_retention_account_id
            if not ret_acc:
                raise UserError(_("Please configure a Retention Receivable account in Settings or on the invoice."))

            # Reduce main receivable line by retention amount, create new line for retention receivable
            current_bal = receivable_line.balance
            ret_bal = self.retention_amount if self.is_inbound() else -self.retention_amount

            # Update main receivable
            receivable_line.with_context(check_move_validity=False).write({
                'balance': current_bal - ret_bal,
                'amount_currency': receivable_line.amount_currency - (
                    self.retention_amount if receivable_line.balance > 0 else -self.retention_amount)
            })

            # Create retention receivable line
            self.env['account.move.line'].with_context(check_move_validity=False).create({
                'move_id': self.id,
                'name': _("Retention Receivable - %s") % self.project_name,
                'account_id': ret_acc.id,
                'partner_id': self.partner_id.id,
                'balance': ret_bal,
                'amount_currency': self.retention_amount if receivable_line.balance > 0 else -self.retention_amount,
                'currency_id': self.currency_id.id,
                'date_maturity': self.handover_date or self.invoice_date,
            })

        # 2. Handle Advance Recovery Reconciliation
        if self.advance_payment_id and self.advance_recovery_amount > 0:
            advance_line = self.advance_payment_id.line_ids.filtered(
                lambda l: l.account_id.account_type == 'asset_receivable' and l.reconciled == False)
            if advance_line and receivable_line:
                # Reconcile receivable line with advance payment line partially
                (receivable_line + advance_line).reconcile()

    def button_draft(self):
        # Clean up retention lines before resetting to draft so reposting doesn't duplicate
        for move in self:
            if move.is_contract_invoice:
                ret_acc = move.retention_account_id or move.company_id.default_retention_account_id
                if ret_acc:
                    ret_lines = move.line_ids.filtered(lambda l: l.account_id == ret_acc)
                    if ret_lines:
                        ret_lines.unlink()
        return super().button_draft()