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

    # Добавляем связь с проектами
    projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="user", cascade="all, delete-orphan"
    )

    # Добавляем связь с тарифом пользователя
    user_tariff: Mapped["UserTariff"] = relationship(
        "UserTariff", back_populates="user", uselist=False, cascade="all, delete-orphan"
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

    user: Mapped["User"] = relationship(
        "User", back_populates="payment_history", uselist=False
    )

    def __repr__(self):
        return f"<PaymentHistory(id={self.id}, user_id={self.user_id}, amount={self.amount})>"


# Таблица для проектов
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    # Связь с пользователем
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"))
    user: Mapped["User"] = relationship("User", back_populates="projects")

    # Связь с чатами
    chats: Mapped[list["ProjectChat"]] = relationship(
        "ProjectChat", back_populates="project", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Project(id={self.id}, name={self.name}, is_active={self.is_active})>"


# Таблица для чатов, привязанных к проектам
class ProjectChat(Base):
    __tablename__ = "project_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[str] = mapped_column(nullable=False)
    chat_title: Mapped[str] = mapped_column(nullable=True)
    chat_type: Mapped[str] = mapped_column(nullable=False)  # группа, канал и т.д.
    is_active: Mapped[bool] = mapped_column(default=True)

    # Связь с проектом
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    project: Mapped["Project"] = relationship("Project", back_populates="chats")

    # Ключевые слова для фильтрации
    keywords: Mapped[str] = mapped_column(nullable=True)

    def __repr__(self):
        return f"<ProjectChat(id={self.id}, chat_id={self.chat_id}, chat_title={self.chat_title})>"


class TariffPlan(Base):
    __tablename__ = "tariff_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(nullable=True)
    price: Mapped[int] = mapped_column(nullable=False)  # Цена в копейках
    max_projects: Mapped[int] = mapped_column(
        nullable=False
    )  # Максимальное количество проектов
    max_chats_per_project: Mapped[int] = mapped_column(
        nullable=False
    )  # Максимальное количество чатов в проекте
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Связь с пользовательскими тарифами
    user_tariffs: Mapped[list["UserTariff"]] = relationship(
        "UserTariff", back_populates="tariff_plan"
    )

    def __repr__(self):
        return f"<TariffPlan(id={self.id}, name={self.name}, price={self.price})>"


class UserTariff(Base):
    __tablename__ = "user_tariffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.user_id"), unique=True)
    tariff_plan_id: Mapped[int] = mapped_column(ForeignKey("tariff_plans.id"))
    start_date: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    end_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True)

    # Связи
    user: Mapped["User"] = relationship("User", back_populates="user_tariff")
    tariff_plan: Mapped["TariffPlan"] = relationship(
        "TariffPlan", back_populates="user_tariffs"
    )

    def __repr__(self):
        return f"<UserTariff(id={self.id}, user_id={self.user_id}, tariff_plan_id={self.tariff_plan_id})>"
