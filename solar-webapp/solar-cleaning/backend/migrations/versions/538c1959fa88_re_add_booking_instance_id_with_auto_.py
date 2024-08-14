"""Re-add booking_instance_id with auto-incrementin bookingModel

Revision ID: 538c1959fa88
Revises: 67dec625f9c9
Create Date: 2024-08-14 17:40:57.618807

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '538c1959fa88'
down_revision = '67dec625f9c9'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.add_column(sa.Column('booking_instance_id', sa.Integer(), autoincrement=True, nullable=False))

    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    with op.batch_alter_table('booking', schema=None) as batch_op:
        batch_op.drop_column('booking_instance_id')

    # ### end Alembic commands ###
