from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(unique=True)

    username: Mapped[str] = mapped_column(nullable=True)
    full_name: Mapped[str] = mapped_column(nullable=True)

    is_active: Mapped[bool] = mapped_column(default=True)
    is_admin: Mapped[bool] = mapped_column(default=False)

    referrer_code: Mapped[str] = mapped_column(
        ForeignKey("referral_links.code"), nullable=True
    )
    referrer: Mapped["ReferralLink"] = relationship(
        "ReferralLink", back_populates="users", uselist=False
    )
    payment_history: Mapped[list["PaymentHistory"]] = relationship(
        "PaymentHistory", back_populates="user"
    )

    balance: Mapped[int] = mapped_column(default=0)

    def __repr__(self):
        return f"User(id={self.id},user_id={self.user_id}, is_admin={self.is_admin}, balance={self.balance})"


class ReferralLink(Base):
    __tablename__ = "referral_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Связь с пользователями
    users: Mapped[list["User"]] = relationship("User", back_populates="referrer")

    def __repr__(self):
        return f"<ReferralLink(code={self.code}, users={len(self.users)})>"


class PaymentHistory(Base):
    __tablename__ = "payment_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    amount: Mapped[int] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="payment_history", uselist=False)

    def __repr__(self):
        return f"<PaymentHistory(id={self.id}, user_id={self.user_id}, amount={self.amount})>"
