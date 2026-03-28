from decimal import Decimal

from sales.accounting import build_trial_balance_rows
from sales.models import AccountLedger


class AccountingService:
    @staticmethod
    def get_trial_balance(*, tenant_alias, as_of_date=None):
        """Return a tenant-scoped trial balance snapshot."""
        return build_trial_balance_rows(alias=tenant_alias, as_of_date=as_of_date)

    @staticmethod
    def get_account_running_balance(*, tenant_alias, account_id):
        latest_row = (
            AccountLedger.objects.using(tenant_alias)
            .filter(account_id=account_id)
            .order_by('-transaction_date', '-id')
            .first()
        )
        if latest_row is None:
            return Decimal('0')
        return latest_row.balance_after
