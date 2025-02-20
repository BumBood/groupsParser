from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column()
    is_admin: Mapped[bool] = mapped_column(default=False)
    balance: Mapped[int] = mapped_column(default=0)

    def __repr__(self):
        return f"User(id={self.id},user_id={self.user_id}, is_admin={self.is_admin}, balance={self.balance})"


class ReferralLink(Base):
    __tablename__ = "referral_links"

    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, nullable=False)
    clicks = Column(Integer, default=0)
    source = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
