"""empty message

Revision ID: 7ebfd3b57d0d
Revises: 46ed2b400c7d
Create Date: 2025-02-21 16:25:35.191884

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7ebfd3b57d0d"
down_revision: Union[str, None] = "46ed2b400c7d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Создаем новую таблицу
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_unique_constraint("uq_users_user_id", ["user_id"])


def downgrade() -> None:
    # Удаляем ограничение
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_user_id", type_="unique")
