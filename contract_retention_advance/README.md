# Contracting Retention & Advance Management (Odoo 19)

A custom Odoo 19 Enterprise module designed for contracting companies in Saudi Arabia. It automates customer retentions, advance recovery tracking, split receivable journal entries, VAT calculations on gross work done, retention releases, and comprehensive reporting.

## Key Features
1. **Configurable Defaults:** Set default retention percentage and Retention Receivable accounts globally via Company Settings.
2. **Invoice-Level Controls:** Input retention % and select unallocated advance payments with percentage or fixed recovery amounts.
3. **Split Accounting Entries:** Automatically routes retention amounts to a dedicated Retention Receivable account with custom handover maturity dates while keeping normal receivables clean.
4. **Automated Advance Matching:** Reconciles advance recovery amounts against customer advance payments with strict balance validations.
5. **Retention Release Wizard:** Move held retention from retention accounts back to normal receivables for collection upon project handover.
6. **Credit Note Reversal & Idempotency:** Safely handles full/partial reversals and prevents duplicate entries when resetting invoices to draft.
7. **Custom QWeb Invoices & Ledger Reports:** Inline-styled PDF reports showing full breakdown of work done, VAT, retention, advance recovery, and net payable.

## Installation
1. Place the `contract_retention_advance` module inside your Odoo addons path.
2. Install the required dependencies: `account`, `sale`, `l10n_sa`.
3. Update your apps list and install **Contracting Retention and Advance Management**.