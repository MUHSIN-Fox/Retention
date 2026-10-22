from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class AccountMove(models.Model):
    _inherit = 'account.move'

    is_contract_invoice = fields.Boolean(string="Contract Retention Invoice", default=False)
    retention_percentage = fields.Float(
        string="Retention %",
        default=lambda self: self.env.company.contract_retention_percentage
    )
    retention_amount = fields.Monetary(
        string="Retention Amount",
        compute='_compute_contract_amounts',
        store=True,
        readonly=False
    )

    advance_payment_id = fields.Many2one(
        'account.payment',
        string="Advance Payment to Recover",
        domain="[('partner_id', '=', partner_id), ('payment_type', '=', 'inbound'), ('state', '=', 'paid')]"
    )
    advance_recovery_type = fields.Selection([
        ('percentage', 'Percentage of Work Done'),
        ('fixed', 'Fixed Amount')
    ], string="Recovery Type", default='percentage')
    advance_recovery_percentage = fields.Float(string="Advance Recovery %", default=20.0)
    advance_recovery_amount = fields.Monetary(
        string="Advance Recovery Amount",
        compute='_compute_contract_amounts',
        store=True,
        readonly=False
    )

    retention_account_id = fields.Many2one(
        'account.account',
        string="Retention Receivable Account",
        default=lambda self: self.env.company.contract_retention_account_id
    )
    handover_date = fields.Date(string="Expected Handover Date")
    project_name = fields.Char(string="Project / Sales Order", compute='_compute_project_name', store=True)

    def _compute_amount(self):
        super()._compute_amount()
        for move in self:
            if move.is_contract_invoice:
                if move.state == 'posted' and move.retention_amount > 0:
                    move.amount_residual = move.amount_residual - move.retention_amount
                    if move.amount_residual_signed:
                        move.amount_residual_signed = move.amount_residual_signed - (
                                move.retention_amount * (-1 if move.direction_sign < 0 else 1)
                        )

    @api.depends('invoice_line_ids', 'invoice_line_ids.sale_line_ids.order_id')
    def _compute_project_name(self):
        for move in self:
            so = move.invoice_line_ids.sale_line_ids.order_id
            if so:
                move.project_name = so.name
            else:
                move.project_name = f"General - {move.partner_id.name}" if move.partner_id else "General"

    @api.depends(
        'is_contract_invoice', 'retention_percentage',
        'advance_recovery_type', 'advance_recovery_percentage', 'amount_untaxed'
    )
    def _compute_contract_amounts(self):
        for move in self:
            if not move.is_contract_invoice:
                move.retention_amount = 0.0
                move.advance_recovery_amount = 0.0
                continue

            base_work_done = move.amount_untaxed  # Work done before tax

            # Retention calculation (percentage of work done)
            if move.retention_percentage:
                move.retention_amount = round(base_work_done * (move.retention_percentage / 100.0), 2)

            # Advance Recovery calculation
            if move.advance_recovery_type == 'percentage':
                move.advance_recovery_amount = round(base_work_done * (move.advance_recovery_percentage / 100.0), 2)

    @api.constrains('advance_payment_id', 'advance_recovery_amount', 'is_contract_invoice')
    def _check_advance_recovery(self):
        for move in self:
            if move.is_contract_invoice and move.advance_payment_id and move.advance_recovery_amount and move.move_type == 'out_invoice':
                payment = move.advance_payment_id
                payment_lines = payment.move_id.line_ids.filtered(
                    lambda l: l.account_id.account_type == 'asset_receivable')
                remaining_advance = abs(sum(payment_lines.mapped('amount_residual')))

                if move.advance_recovery_amount > remaining_advance + 0.01:
                    raise ValidationError(
                        _("Advance recovery amount (%.2f) exceeds remaining advance balance (%.2f) on payment %s.") %
                        (move.advance_recovery_amount, remaining_advance, payment.name))

    def _post(self, soft=True):
        res = super()._post(soft=soft)
        for move in res:
            if move.is_contract_invoice and move.move_type in ('out_invoice', 'out_refund'):
                move._process_contract_posting_splits()
        return res

    def _process_contract_posting_splits(self):
        """Adjusts journal entry lines: splits retention into retention account and matches/reverses advance recovery."""
        self.ensure_one()
        if not self.retention_amount and not self.advance_recovery_amount:
            return

        receivable_line = self.line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable' and not l.tax_line_id
        )
        print(receivable_line.read())
        if not receivable_line:
            return

        is_refund = self.move_type in ('out_refund', 'in_refund')
        multiplier = -1 if is_refund else 1

        # 1. Handle Retention Split
        if self.retention_amount > 0:
            ret_acc = self.retention_account_id or self.company_id.contract_retention_account_id
            if not ret_acc:
                raise UserError(_("Please configure a Retention Receivable account in Settings or on the invoice."))
            if not is_refund:
                ret_bal = self.retention_amount * multiplier

                new_receivable_balance = receivable_line.balance - ret_bal
                new_receivable_residual = receivable_line.amount_residual - ret_bal

                receivable_line.with_context(check_move_validity=False).write({
                    'balance': new_receivable_balance,
                    'amount_residual': new_receivable_residual,
                    'amount_currency': receivable_line.amount_currency - (
                            self.retention_amount * (-1 if receivable_line.balance < 0 else 1)),
                    'amount_residual_currency': receivable_line.amount_residual_currency - (
                            self.retention_amount * (-1 if receivable_line.balance < 0 else 1))
                })
            else:
                ret_bal = self.retention_amount * multiplier

                new_receivable_balance = receivable_line.balance - ret_bal
                new_receivable_residual = receivable_line.amount_residual - ret_bal

                currency_adjustment = self.retention_amount * multiplier * (-1 if receivable_line.balance < 0 else 1)

                receivable_line.with_context(check_move_validity=False).write({
                    'account_id': self.partner_id.property_account_receivable_id.id,
                    'partner_id': self.partner_id.id,
                    'balance': new_receivable_balance,
                    'amount_residual': new_receivable_residual,
                    'amount_currency': receivable_line.amount_currency - currency_adjustment,
                    'amount_residual_currency': receivable_line.amount_residual_currency - currency_adjustment
                })
            self.env['account.move.line'].with_context(check_move_validity=False).create({
                'move_id': self.id,
                'name': _("Retention Receivable - %s") % self.project_name,
                'account_id': ret_acc.id,
                'partner_id': self.partner_id.id,
                'balance': ret_bal,
                'amount_residual': ret_bal,
                'amount_currency': self.retention_amount * (-1 if receivable_line.balance < 0 else 1),
                'amount_residual_currency': self.retention_amount * (-1 if receivable_line.balance < 0 else 1),
                'currency_id': self.currency_id.id,
                'date_maturity': self.handover_date or self.invoice_date,
            })

        # 2. Handle Advance Recovery & Credit Note Reversal
        if self.advance_recovery_amount > 0:
            if not is_refund and self.advance_payment_id:
                # Normal Invoice: Create partial reconciliation with advance payment
                advance_line = self.advance_payment_id.move_id.line_ids.filtered(
                    lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled
                )
                if advance_line and receivable_line:
                    debit_line = receivable_line if receivable_line.balance > 0 else advance_line
                    credit_line = advance_line if receivable_line.balance > 0 else receivable_line

                    self.env['account.partial.reconcile'].create({
                        'debit_move_id': debit_line.id,
                        'credit_move_id': credit_line.id,
                        'amount': self.advance_recovery_amount,
                        'debit_amount_currency': self.advance_recovery_amount if debit_line.currency_id else 0.0,
                        'credit_amount_currency': self.advance_recovery_amount if credit_line.currency_id else 0.0,
                    })
            elif is_refund:
                # Credit Note: Reduce/remove proportional partial reconciliations from the reversed invoice
                reversed_invoice = self.reversed_entry_id
                if reversed_invoice:
                    partials = self.env['account.partial.reconcile'].search([
                        '|',
                        ('debit_move_id.move_id', '=', reversed_invoice.id),
                        ('credit_move_id.move_id', '=', reversed_invoice.id)
                    ])
                    remaining_to_unreconcile = self.advance_recovery_amount
                    for partial in partials:
                        if remaining_to_unreconcile <= 0:
                            break
                        deduct_amt = min(partial.amount, remaining_to_unreconcile)
                        if deduct_amt >= partial.amount:
                            partial.unlink()
                        else:
                            partial.write({'amount': partial.amount - deduct_amt})
                        remaining_to_unreconcile -= deduct_amt

                # Adjust receivable line for credit note advance recovery adjustment
                adv_bal = self.advance_recovery_amount * multiplier
                receivable_line.with_context(check_move_validity=False).write({
                    'balance': receivable_line.balance - adv_bal,
                    'amount_residual': receivable_line.amount_residual - adv_bal,
                })

            self.invalidate_recordset(['amount_paid', 'amount_residual', 'payment_state'])

    def button_draft(self):
        # 1. Transition the entry to draft state first so Odoo allows line modifications/deletions
        res = super().button_draft()

        for move in self:
            if move.is_contract_invoice:
                is_refund = move.move_type in ('out_refund', 'in_refund')
                multiplier = -1 if is_refund else 1

                receivable_line = move.line_ids.filtered(
                    lambda l: l.account_id.account_type == 'asset_receivable' and not l.tax_line_id
                )[:1]

                # 2. Restore main receivable balance and currency values from retention
                ret_acc = move.retention_account_id or move.company_id.contract_retention_account_id
                if ret_acc and receivable_line and move.retention_amount > 0:
                    ret_bal = move.retention_amount * multiplier
                    currency_adjustment = move.retention_amount * multiplier * (
                        -1 if receivable_line.balance < 0 else 1)

                    receivable_line.with_context(check_move_validity=False).write({
                        'balance': receivable_line.balance + ret_bal,
                        'amount_residual': receivable_line.amount_residual + ret_bal,
                        'amount_currency': receivable_line.amount_currency + currency_adjustment,
                        'amount_residual_currency': receivable_line.amount_residual_currency + currency_adjustment
                    })

                    ret_lines = move.line_ids.filtered(lambda l: l.account_id == ret_acc)
                    if ret_lines:
                        ret_lines.with_context(dynamic_unlink=True).sudo().unlink()

                # 3. Restore main receivable balance from advance recovery and clean partials
                if move.advance_recovery_amount > 0:
                    if is_refund:
                        adv_bal = move.advance_recovery_amount * multiplier
                        if receivable_line:
                            receivable_line.with_context(check_move_validity=False).write({
                                'balance': receivable_line.balance + adv_bal,
                                'amount_residual': receivable_line.amount_residual + adv_bal,
                            })

                    partials = self.env['account.partial.reconcile'].search([
                        '|',
                        ('debit_move_id.move_id', '=', move.id),
                        ('credit_move_id.move_id', '=', move.id)
                    ])
                    partials.sudo().unlink()

        return res