from odoo import api, fields, models, _
import io
import base64
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


class RetentionAdvanceReportWizard(models.TransientModel):
    _name = 'retention.advance.report.wizard'
    _description = 'Retention and Advance Report Wizard'

    as_at_date = fields.Date(string="As at Date", required=True, default=fields.Date.context_today)
    partner_ids = fields.Many2many('res.partner', string="Customers")
    project_name = fields.Char(string="Project / Sales Order")

    def action_export_excel(self):
        # 1. Create workbook in memory
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Retention & Advance Summary"
        ws.views.sheetView[0].showGridLines = True

        # Title block
        ws.merge_cells("A1:I1")
        ws['A1'] = "Customer & Project Retention & Advance Balance Report"
        ws['A1'].font = Font(name="Calibri", size=16, bold=True, color="1F497D")
        ws['A1'].alignment = Alignment(horizontal="left", vertical="center")

        ws['A2'] = "As at Date:"
        ws['A2'].font = Font(name="Calibri", size=11, bold=True, color="595959")
        ws['B2'] = str(self.as_at_date)
        ws['B2'].font = Font(name="Calibri", size=11, italic=True)

        # Headers
        headers = [
            "Customer Name", "Project / Reference", "Total Invoiced",
            "Retention Held", "Retention Released", "Retention Balance",
            "Advance Received", "Advance Recovered", "Advance Balance"
        ]

        header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        left_align = Alignment(horizontal="left", vertical="center")
        right_align = Alignment(horizontal="right", vertical="center")

        thin_border_side = Side(border_style="thin", color="D9D9D9")
        thin_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
        thick_top_double_bottom = Border(top=Side(border_style="thin", color="000000"), bottom=Side(border_style="double", color="000000"))

        for col_num, header_title in enumerate(headers, 1):
            cell = ws.cell(row=4, column=col_num)
            cell.value = header_title
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center_align
            cell.border = thin_border

        ws.row_dimensions[4].height = 28

        # 2. Fetch Moves (Invoices & Credit Notes)
        domain = [
            ('state', '=', 'posted'),
            ('invoice_date', '<=', self.as_at_date),
            ('is_contract_invoice', '=', True),
            ('move_type', 'in', ('out_invoice', 'out_refund'))
        ]
        if self.partner_ids:
            domain.append(('partner_id', 'in', self.partner_ids.ids))
        if self.project_name:
            domain.append(('project_name', 'ilike', self.project_name))

        moves = self.env['account.move'].search(domain)

        grouped_data = {}
        for move in moves:
            key = (move.partner_id.name or 'Unknown', move.project_name or 'General')
            if key not in grouped_data:
                grouped_data[key] = {
                    'total_invoiced': 0.0,
                    'retention_held': 0.0,
                    'retention_released': 0.0,
                    'advance_received': 0.0,
                    'advance_recovered': 0.0,
                }

            sign = -1 if move.move_type == 'out_refund' else 1
            grouped_data[key]['total_invoiced'] += move.amount_untaxed * sign
            grouped_data[key]['retention_held'] += move.retention_amount * sign
            grouped_data[key]['advance_recovered'] += move.amount_total - move.amount_residual -move.retention_amount * sign
            print(key)
            print(move.read())
        # 3. Fetch Advance Payments (FIXXED: state='posted')
        pay_domain = [
            ('state', '=', 'paid'),
            ('date', '<=', self.as_at_date),
            ('payment_type', '=', 'inbound')
        ]
        if self.partner_ids:
            pay_domain.append(('partner_id', 'in', self.partner_ids.ids))

        payments = self.env['account.payment'].search(pay_domain)
        for pay in payments:
            partner_name = pay.partner_id.name or 'Unknown'
            # Match existing group key for partner or fallback to General
            matching_keys = [k for k in grouped_data.keys() if k[0] == partner_name]
            if matching_keys:
                for k in matching_keys:
                    grouped_data[k]['advance_received'] += pay.amount
            else:
                key = (partner_name, 'General')
                if key not in grouped_data:
                    grouped_data[key] = {
                        'total_invoiced': 0.0,
                        'retention_held': 0.0,
                        'retention_released': 0.0,
                        'advance_received': pay.amount,
                        'advance_recovered': 0.0,
                    }
                else:
                    grouped_data[key]['advance_received'] += pay.amount

        # 4. Populate Excel Rows
        row_start = 5
        num_fmt = "$#,##0.00"
        zebra_fill = PatternFill(start_color="F9FAFB", end_color="F9FAFB", fill_type="solid")

        for i, ((customer, project), val) in enumerate(grouped_data.items()):

            current_row = row_start + i

            ws.cell(row=current_row, column=1, value=customer).alignment = left_align
            ws.cell(row=current_row, column=2, value=project).alignment = left_align

            ws.cell(row=current_row, column=3, value=val['total_invoiced'])
            ws.cell(row=current_row, column=4, value=val['retention_held'])
            ws.cell(row=current_row, column=5, value=val['retention_released'])

            # Retention Balance Formula = Held - Released
            ws.cell(row=current_row, column=6, value=f"=D{current_row}-E{current_row}")

            ws.cell(row=current_row, column=7, value=val['advance_received'])
            ws.cell(row=current_row, column=8, value=val['advance_recovered'])

            # Advance Balance Formula = Received - Recovered
            ws.cell(row=current_row, column=9, value=f"=G{current_row}-H{current_row}")

            for col in range(1, 10):
                cell = ws.cell(row=current_row, column=col)
                cell.border = thin_border
                if i % 2 == 1:
                    cell.fill = zebra_fill
                if col in range(3, 10):
                    cell.number_format = num_fmt
                    cell.alignment = right_align

        # 5. Total Row
        tot_row = row_start + len(grouped_data) if grouped_data else row_start
        ws.cell(row=tot_row, column=1, value="Total").font = Font(name="Calibri", size=11, bold=True)
        ws.cell(row=tot_row, column=1).alignment = left_align

        for col in range(3, 10):
            col_letter = get_column_letter(col)
            cell = ws.cell(row=tot_row, column=col, value=f"=SUM({col_letter}{row_start}:{col_letter}{tot_row - 1})")
            cell.font = Font(name="Calibri", size=11, bold=True)
            cell.number_format = num_fmt
            cell.alignment = right_align

        for col in range(1, 10):
            ws.cell(row=tot_row, column=col).border = thick_top_double_bottom

        # Auto-adjust column widths
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 15)

        # Output Stream & Download
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        attachment = self.env['ir.attachment'].create({
            'name': f'Retention_Advance_Report_{self.as_at_date}.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }