from .tenant_context import get_current_tenant_db_alias


class TenantDatabaseRouter:
    SALES_APP = 'sales'
    PLATFORM_MODELS = {
        ('sales', 'platformtenant'),
        ('sales', 'globalauditlog'),
        ('sales', 'tenantbackuprecord'),
        ('sales', 'tenantmigrationrecord'),
        ('sales', 'userthemepreference'),
    }
    SESSION_APP = 'sessions'

    def _is_platform_model(self, app_label, model_name):
        return (app_label, model_name) in self.PLATFORM_MODELS

    def _is_tenant_alias(self, alias):
        return bool(alias and alias.startswith('tenant_'))

    def db_for_read(self, model, **hints):
        app_label = model._meta.app_label
        model_name = model._meta.model_name

        if app_label == self.SESSION_APP:
            return 'default'

        if self._is_platform_model(app_label, model_name):
            return 'default'

        tenant_alias = get_current_tenant_db_alias()
        if tenant_alias:
            return tenant_alias

        return None

    def db_for_write(self, model, **hints):
        app_label = model._meta.app_label
        model_name = model._meta.model_name

        if app_label == self.SESSION_APP:
            return 'default'

        if self._is_platform_model(app_label, model_name):
            return 'default'

        tenant_alias = get_current_tenant_db_alias()
        if tenant_alias:
            return tenant_alias

        return None

    def allow_relation(self, obj1, obj2, **hints):
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == self.SESSION_APP:
            return db == 'default'

        if app_label == self.SALES_APP and model_name:
            if self._is_platform_model(app_label, model_name):
                return db == 'default'
            return self._is_tenant_alias(db)

        if app_label == self.SALES_APP and model_name is None:
            # Keep historical data-migration behavior stable while still
            # enforcing model-level isolation above.
            return db == 'default' or self._is_tenant_alias(db)

        if self._is_tenant_alias(db):
            return True

        return True
