"""Keep one application account per provider identity."""

from alembic import op

revision = "b1267d4e901a"
down_revision = "73ec80fa95de"
branch_labels = None
depends_on = None


def upgrade():
    # If historical duplicate identities exist, fail rather than silently delete
    # accounts or choose an owner. An operator must resolve them explicitly.
    op.create_index(
        "uq_oauth_provider_account", "oauth_account", ["oauth_name", "account_id"], unique=True
    )


def downgrade():
    op.drop_index("uq_oauth_provider_account", table_name="oauth_account")
