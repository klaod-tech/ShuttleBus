"""staff_accounts_login_hardening — 로그인 시도 제한·토큰 즉시 차단 (IMPROVEMENTS 한계 1·2, 2026-09-18)

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('staff_accounts', sa.Column('failed_login_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('staff_accounts', sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('staff_accounts', sa.Column('token_not_before', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('staff_accounts', 'token_not_before')
    op.drop_column('staff_accounts', 'locked_until')
    op.drop_column('staff_accounts', 'failed_login_count')
