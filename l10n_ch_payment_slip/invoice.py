# -*- coding: utf-8 -*-
##############################################################################
#
#    Author: Nicolas Bessi. Copyright Camptocamp SA
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from openerp import models, fields, api


class AccountMoveLine(models.Model):

    _inherit = "account.move.line"

    transaction_ref = fields.Char('Transaction Ref.')


class AccountInvoice(models.Model):
    """Inherit account.invoice in order to add bvr
    printing functionnalites. BVR is a Swiss payment vector"""

    _inherit = "account.invoice"

    @api.model
    def _get_reference_type(self):
        """Function used by the function field 'reference_type'
        in order to initalise available BVR Reference Types
        """
        res = super(AccountInvoice, self)._get_reference_type()
        res.append(('bvr', 'BVR'))
        return res

    reference = fields.Char(copy=False)

    reference_type = fields.Selection(
        _get_reference_type,
        string='Reference Type',
        required=True
    )

    partner_bank_id = fields.Many2one(
        'res.partner.bank',
        'Bank Account',
        help='The partner bank account to pay\n'
        'Keep empty to use the default'
    )

    bvr_reference = fields.Text(
        string='BVR ref',
        compute='_compute_full_bvr_name',
        store=True,
    )

    slip_ids = fields.One2many(
        string='Related slip',
        comodel_name='l10n_ch.payment_slip',
        inverse_name='invoice_id'
    )

    @api.one
    @api.depends('slip_ids', 'state')
    def _compute_full_bvr_name(self):
        """Concatenate related slip references

        :return: reference comma separated
        :rtype: str
        """
        if not self.slip_ids:
            return ''
        self.bvr_reference = ','.join(x.reference for x in self.slip_ids)

    def get_payment_move_line(self):
        """Return the move line related to current invoice slips

        :return: recordset of `account.move.line`
        :rtype: :py:class:`openerp.model.Models`
        """
        move_line_model = self.env['account.move.line']
        account_model = self.env['account.account']
        tier_accounts = account_model.search(
            [('type', 'in', ['receivable', 'payable'])],
        )
        return move_line_model.search(
            [('move_id', '=', self.move_id.id),
             ('account_id', 'in', tier_accounts.mapped('id'))]
        )

    @api.model
    def _update_ref_on_account_analytic_line(self, ref, move_id):
        """Propagate reference on analytic line"""
        self.env.cr.execute(
            'UPDATE account_analytic_line SET ref=%s'
            '   FROM account_move_line '
            ' WHERE account_move_line.move_id = %s '
            '   AND account_analytic_line.move_id = account_move_line.id',
            (ref, move_id)
        )
        return True

    @api.model
    def _action_bvr_number_move_line(self, move_line, ref):
        """Propagate reference on move lines and analytic lines"""
        if not ref:
            return
        self.env.cr.execute('UPDATE account_move_line SET transaction_ref=%s'
                            '  WHERE id=%s', (ref, move_line.id))
        self._update_ref_on_account_analytic_line(ref, move_line.move_id.id)
        self.env.invalidate_all()

    @api.multi
    def action_number(self):
        """ Copy the BVR/ESR reference in the transaction_ref of move lines.

        For customers invoices: the BVR reference is computed using
        ``get_bvr_ref()`` on the invoice or move lines.

        For suppliers invoices: the BVR reference is stored in the reference
        field of the invoice.

        """
        res = super(AccountInvoice, self).action_number()
        pay_slip = self.env['l10n_ch.payment_slip']
        for inv in self:
            for pay_slip in pay_slip.compute_pay_slips_from_invoices(inv):
                if inv.type in ('out_invoice', 'out_refund'):
                    ref = pay_slip.reference
                elif inv.reference_type == 'bvr' and inv.reference:
                    ref = inv.reference
                else:
                    ref = False
                self._action_bvr_number_move_line(pay_slip.move_line_id,
                                                  ref)
        return res
