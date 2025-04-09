from typing import Optional, List
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from datetime import datetime, timedelta

from db.models import (
    PaymentHistory,
    User,
    Base,
    ReferralLink,
    Project,
    ProjectChat,
    TariffPlan,
    UserTariff,
)


class Database:
    def __init__(self, db_path: str = "database.db") -> None:
        # Получаем абсолютный путь к файлу БД
        base_dir = os.path.dirname(os.path.abspath(__file__))
        db_url = f"sqlite:///{os.path.join(base_dir, db_path)}"

        # Создаем движок базы данных
        self.engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},  # Важно для SQLite
        )

        # Создаем все таблицы
        Base.metadata.create_all(self.engine)

        # Создаем фабрику сессий
        self.SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

    def get_session(self) -> Session:
        """Создает новую сессию для работы с БД"""
        return self.SessionLocal()

    def get_user(self, user_id: int) -> Optional[User]:
        """Получает пользователя по его user_id"""
        with self.get_session() as session:
            return session.query(User).filter(User.user_id == user_id).first()

    def create_zero_tariff(self) -> TariffPlan:
        """Создает нулевой тариф, если его еще нет"""
        with self.get_session() as session:
            zero_tariff = (
                session.query(TariffPlan).filter(TariffPlan.name == "Zero").first()
            )
            if not zero_tariff:
                zero_tariff = TariffPlan(
                    name="Zero",
                    price=0,
                    max_projects=1,
                    max_chats_per_project=1,
                    description="Базовый тариф для новых пользователей",
                    is_active=True,
                )
                session.add(zero_tariff)
                session.commit()
                session.refresh(zero_tariff)
            return zero_tariff

    def get_or_create_or_update_user(
        self, user_id: int, username: str, full_name: str, referrer_code: str = None
    ) -> User:
        """Получает существующего пользователя или создает нового, обновляет пустые данные"""
        is_new = False
        user = self.get_user(user_id)

        with self.get_session() as session:
            if user is None:
                user = User(user_id=user_id, referrer_code=referrer_code)
                is_new = True
                # Создаем нулевой тариф для нового пользователя
                zero_tariff = self.create_zero_tariff()
                user_tariff = UserTariff(
                    user_id=user_id,
                    tariff_plan_id=zero_tariff.id,
                    end_date=datetime.now() + timedelta(days=36500),  # ~100 лет
                    is_active=True,
                )
                session.add(user_tariff)
            if user.username is None:
                user.username = username
            if user.full_name is None:
                user.full_name = full_name
            session.add(user)
            session.commit()
            session.refresh(user)

        return user, is_new

    def get_all_users(self) -> list[User]:
        """Получает всех пользователей"""
        with self.get_session() as session:
            return session.query(User).all()

    def update_balance(self, user_id: int, amount: int) -> User:
        """Изменяет баланс пользователя"""
        with self.get_session() as session:
            user = session.query(User).filter(User.user_id == user_id).first()
            if user:
                user.balance += amount
                session.commit()
                session.refresh(user)
            return user

    def set_admin(self, user_id: int, is_admin: bool = True) -> User:
        """Устанавливает/снимает права администратора"""
        with self.get_session() as session:
            user = session.query(User).filter(User.user_id == user_id).first()
            if user:
                user.is_admin = is_admin
                session.commit()
                session.refresh(user)
            return user

    def get_admins(self) -> list[User]:
        """Получает всех администраторов"""
        with self.get_session() as session:
            return session.query(User).filter(User.is_admin).all()

    def update_user_activity(self, user_id: int, is_active: bool) -> User:
        """Обновляет статус активности пользователя"""
        with self.get_session() as session:
            user = session.query(User).filter(User.user_id == user_id).first()
            if user:
                user.is_active = is_active
                session.commit()
                session.refresh(user)
            return user

    def create_referral_link(self, code: str) -> ReferralLink:
        # sourcery skip: class-extract-method
        """Создает новую реферальную ссылку"""
        with self.get_session() as session:
            ref_link = ReferralLink(code=code, created_at=func.now())
            session.add(ref_link)
            session.commit()
            session.refresh(ref_link)
            return ref_link

    def get_referral_clicks(self, code: str) -> int:
        """Получает количество кликов (пользователей) для реферальной ссылки"""
        with self.get_session() as session:
            ref_link = (
                session.query(ReferralLink).filter(ReferralLink.code == code).first()
            )
            return len(ref_link.users) if ref_link else 0

    def get_referral_link(self, code: str) -> Optional[ReferralLink]:
        """Получает информацию о реферальной ссылке"""
        with self.get_session() as session:
            return session.query(ReferralLink).filter(ReferralLink.code == code).first()

    def get_or_create_referral_link(self, code: str) -> ReferralLink:
        """Получает существующую реферальную ссылку или создает новую"""
        with self.get_session() as session:
            ref_link = (
                session.query(ReferralLink).filter(ReferralLink.code == code).first()
            )
            if ref_link:
                return ref_link

            ref_link = ReferralLink(code=code, created_at=func.now())
            session.add(ref_link)
            session.commit()
            session.refresh(ref_link)
            return ref_link

    def get_all_referral_links(self) -> List[ReferralLink]:
        """Получает все реферальные ссылки, отсортированные по количеству пользователей"""
        with self.get_session() as session:
            return (
                session.query(ReferralLink)
                .outerjoin(User)
                .group_by(ReferralLink.id)
                .order_by(func.count(User.id).desc())
                .all()
            )

    def get_all_referral_links_statistics(self) -> list[dict]:
        """Получает статистику по всем реферальным ссылкам"""
        return [
            self.get_link_statistics(link.code)
            for link in self.get_all_referral_links()
        ]

    def get_link_statistics(self, code: str) -> dict:
        """Получает статистику по конкретной реферальной ссылке"""
        with self.get_session() as session:
            link = session.query(ReferralLink).filter(ReferralLink.code == code).first()
            if not link:
                return None

            total_payments = sum(
                sum(payment.amount for payment in user.payment_history)
                for user in link.users
            )

            return {
                "code": link.code,
                "users_count": len(link.users),
                "total_payments": total_payments,
                "created_at": link.created_at,
            }

    def delete_referral_link(self, code: str) -> bool:
        """Удаляет реферальную ссылку"""
        with self.get_session() as session:
            link = session.query(ReferralLink).filter(ReferralLink.code == code).first()
            if link and len(link.users) == 0:
                session.delete(link)
                session.commit()
                return True
            return False

    def make_payment(self, user_id: int, amount: int) -> PaymentHistory:
        """Создает запись о платеже"""
        with self.get_session() as session:
            payment = PaymentHistory(user_id=user_id, amount=amount)
            session.add(payment)
            session.commit()
            session.refresh(payment)
            return payment

    def get_payment(self, payment_id: int) -> PaymentHistory:
        """Получает платеж по его id"""
        with self.get_session() as session:
            return (
                session.query(PaymentHistory)
                .filter(PaymentHistory.id == payment_id)
                .first()
            )

    def get_all_payments(self) -> list[PaymentHistory]:
        """Получает все платежи"""
        with self.get_session() as session:
            return session.query(PaymentHistory).all()

    # ---------- МЕТОДЫ ДЛЯ РАБОТЫ С ПРОЕКТАМИ ----------

    def create_project(
        self, user_id: int, name: str, description: str = None, is_active: bool = True
    ) -> Project:
        """Создает новый проект для пользователя"""
        with self.get_session() as session:
            project = Project(
                user_id=user_id, name=name, description=description, is_active=is_active
            )
            session.add(project)
            session.commit()
            session.refresh(project)
            return project

    def get_project(self, project_id: int) -> Optional[Project]:
        """Получает проект по его id"""
        with self.get_session() as session:
            return session.query(Project).filter(Project.id == project_id).first()

    def get_user_projects(
        self, user_id: int, active_only: bool = False
    ) -> List[Project]:
        """Получает все проекты пользователя"""
        with self.get_session() as session:
            query = session.query(Project).filter(Project.user_id == user_id)
            if active_only:
                query = query.filter(Project.is_active == True)  # noqa: E712
            return query.all()  # Убрана сортировка по created_at

    def update_project(self, project_id: int, **kwargs) -> Optional[Project]:
        """Обновляет данные проекта"""
        with self.get_session() as session:
            project = session.query(Project).filter(Project.id == project_id).first()
            if project:
                for key, value in kwargs.items():
                    if hasattr(project, key):
                        setattr(project, key, value)
                session.commit()
                session.refresh(project)
                return project
            return None

    def toggle_project_status(self, project_id: int) -> Optional[Project]:
        """Включает/выключает проект"""
        with self.get_session() as session:
            project = session.query(Project).filter(Project.id == project_id).first()
            if project:
                project.is_active = not project.is_active
                session.commit()
                session.refresh(project)
                return project
            return None

    def delete_project(self, project_id: int) -> bool:
        """Удаляет проект и все связанные с ним чаты"""
        with self.get_session() as session:
            project = session.query(Project).filter(Project.id == project_id).first()
            if project:
                session.delete(project)
                session.commit()
                return True
            return False

    # ---------- МЕТОДЫ ДЛЯ РАБОТЫ С ЧАТАМИ ПРОЕКТОВ ----------

    def add_chat_to_project(
        self,
        project_id: int,
        chat_id: str,
        chat_title: str = None,
        chat_type: str = "group",
        keywords: str = None,
    ) -> ProjectChat:
        """Добавляет чат в проект"""
        with self.get_session() as session:
            # Проверяем, существует ли уже такой чат в проекте
            existing_chat = (
                session.query(ProjectChat)
                .filter(
                    ProjectChat.project_id == project_id, ProjectChat.chat_id == chat_id
                )
                .first()
            )

            if existing_chat:
                return existing_chat

            chat = ProjectChat(
                project_id=project_id,
                chat_id=chat_id,
                chat_title=chat_title,
                chat_type=chat_type,
                keywords=keywords,
            )
            session.add(chat)
            session.commit()
            session.refresh(chat)
            return chat

    def get_project_chats(
        self, project_id: int, active_only: bool = False
    ) -> List[ProjectChat]:
        """Получает все чаты проекта"""
        with self.get_session() as session:
            query = session.query(ProjectChat).filter(
                ProjectChat.project_id == project_id
            )
            if active_only:
                query = query.filter(ProjectChat.is_active == True)  # noqa: E712
            return query.all()

    def update_chat(self, chat_id: int, **kwargs) -> Optional[ProjectChat]:
        """Обновляет данные чата"""
        with self.get_session() as session:
            chat = session.query(ProjectChat).filter(ProjectChat.id == chat_id).first()
            if chat:
                for key, value in kwargs.items():
                    if hasattr(chat, key):
                        setattr(chat, key, value)
                session.commit()
                session.refresh(chat)
                return chat
            return None

    def delete_chat(self, chat_id: int) -> bool:
        """Удаляет чат из проекта"""
        with self.get_session() as session:
            chat = session.query(ProjectChat).filter(ProjectChat.id == chat_id).first()
            if chat:
                session.delete(chat)
                session.commit()
                return True

    def toggle_chat_status(self, chat_id: int) -> Optional[ProjectChat]:
        """Включает/выключает чат в проекте"""
        with self.get_session() as session:
            chat = session.query(ProjectChat).filter(ProjectChat.id == chat_id).first()
            if chat:
                chat.is_active = not chat.is_active
                session.commit()
                session.refresh(chat)
                return chat
            return None

    def update_chat_activity(
        self, chat_id: int, is_active: bool
    ) -> Optional[ProjectChat]:
        """Устанавливает конкретное значение активности чата"""
        with self.get_session() as session:
            chat = session.query(ProjectChat).filter(ProjectChat.id == chat_id).first()
            if chat:
                chat.is_active = is_active
                session.commit()
                session.refresh(chat)
                return chat
            return None

    def delete_chat_from_project(self, chat_id: int) -> bool:
        """Удаляет чат из проекта"""
        with self.get_session() as session:
            chat = session.query(ProjectChat).filter(ProjectChat.id == chat_id).first()
            if chat:
                session.delete(chat)
                session.commit()
                return True
            return False

    def get_chat(self, chat_id: int) -> Optional[ProjectChat]:
        """Получает чат по его id"""
        with self.get_session() as session:
            return session.query(ProjectChat).filter(ProjectChat.id == chat_id).first()

    def get_all_active_projects(self) -> List[Project]:
        """Получает все активные проекты"""
        with self.get_session() as session:
            return (
                session.query(Project).filter(Project.is_active == True).all()
            )  # noqa: E712

    def update_chat_keywords(
        self, chat_id: int, keywords: str
    ) -> Optional[ProjectChat]:
        """Обновляет ключевые слова для фильтрации сообщений в чате"""
        with self.get_session() as session:
            chat = session.query(ProjectChat).filter(ProjectChat.id == chat_id).first()
            if chat:
                chat.keywords = keywords
                session.commit()
                session.refresh(chat)
                return chat
            return None

    # Функции для работы с тарифами
    def create_tariff_plan(
        self,
        name: str,
        price: int,
        max_projects: int,
        max_chats_per_project: int,
        description: str = None,
    ) -> TariffPlan:
        """Создает новый тарифный план"""
        with self.get_session() as session:
            tariff = TariffPlan(
                name=name,
                price=price,
                max_projects=max_projects,
                max_chats_per_project=max_chats_per_project,
                description=description,
            )
            session.add(tariff)
            session.commit()
            session.refresh(tariff)
            return tariff

    def get_tariff_plan(self, tariff_id: int) -> Optional[TariffPlan]:
        """Получает тарифный план по ID"""
        with self.get_session() as session:
            return session.query(TariffPlan).filter(TariffPlan.id == tariff_id).first()

    def get_all_tariff_plans(self, active_only: bool = False) -> List[TariffPlan]:
        """Получает все тарифные планы"""
        with self.get_session() as session:
            query = session.query(TariffPlan)
            if active_only:
                query = query.filter(TariffPlan.is_active == True)
            return query.all()

    def update_tariff_plan(self, tariff_id: int, **kwargs) -> Optional[TariffPlan]:
        """Обновляет тарифный план"""
        with self.get_session() as session:
            tariff = (
                session.query(TariffPlan).filter(TariffPlan.id == tariff_id).first()
            )
            if tariff:
                for key, value in kwargs.items():
                    if hasattr(tariff, key):
                        setattr(tariff, key, value)
                session.commit()
                session.refresh(tariff)
            return tariff

    def toggle_tariff_status(self, tariff_id: int) -> Optional[TariffPlan]:
        """Переключает статус активности тарифа"""
        with self.get_session() as session:
            tariff = (
                session.query(TariffPlan).filter(TariffPlan.id == tariff_id).first()
            )
            if tariff:
                tariff.is_active = not tariff.is_active
                session.commit()
                session.refresh(tariff)
            return tariff

    def delete_tariff_plan(self, tariff_id: int) -> bool:
        """Удаляет тарифный план"""
        with self.get_session() as session:
            tariff = (
                session.query(TariffPlan).filter(TariffPlan.id == tariff_id).first()
            )
            if tariff:
                session.delete(tariff)
                session.commit()
                return True
            return False

    def assign_tariff_to_user(
        self, user_id: int, tariff_id: int, duration_days: int = 30
    ) -> Optional[UserTariff]:
        """Назначает тариф пользователю"""
        with self.get_session() as session:
            # Получаем пользователя и тариф
            user = session.query(User).filter(User.user_id == user_id).first()
            tariff = (
                session.query(TariffPlan).filter(TariffPlan.id == tariff_id).first()
            )

            if not user or not tariff:
                return None

            # Проверяем существующий тариф
            existing_tariff = (
                session.query(UserTariff).filter(UserTariff.user_id == user_id).first()
            )

            if existing_tariff:
                # Обновляем существующий тариф
                existing_tariff.tariff_plan_id = tariff_id
                existing_tariff.start_date = datetime.now()
                existing_tariff.end_date = datetime.now() + timedelta(
                    days=duration_days
                )
                existing_tariff.is_active = True
                session.commit()
                session.refresh(existing_tariff)
                return existing_tariff
            else:
                # Создаем новый тариф
                user_tariff = UserTariff(
                    user_id=user_id,
                    tariff_plan_id=tariff_id,
                    end_date=datetime.now() + timedelta(days=duration_days),
                    is_active=True,
                )
                session.add(user_tariff)
                session.commit()
                session.refresh(user_tariff)
                return user_tariff

    def get_user_tariff(self, user_id: int) -> Optional[UserTariff]:
        """Получает активный тариф пользователя"""
        with self.get_session() as session:
            user_tariff = (
                session.query(UserTariff)
                .filter(UserTariff.user_id == user_id, UserTariff.is_active == True)
                .first()
            )

            # Если тариф найден, проверяем, не истек ли срок его действия
            if user_tariff and user_tariff.end_date <= datetime.now():
                # Тариф истек, деактивируем его
                user_tariff.is_active = False
                session.commit()
                return None

            return user_tariff

    def deactivate_user_tariff(self, user_id: int) -> bool:
        """Деактивирует тариф пользователя"""
        with self.get_session() as session:
            user_tariff = (
                session.query(UserTariff)
                .filter(UserTariff.user_id == user_id, UserTariff.is_active == True)
                .first()
            )

            if user_tariff:
                user_tariff.is_active = False
                session.commit()
                return True
            return False

    def get_user_tariff_info(self, user_id: int) -> dict:
        """Получает полную информацию о тарифе пользователя"""
        with self.get_session() as session:
            user_tariff = (
                session.query(UserTariff)
                .filter(UserTariff.user_id == user_id, UserTariff.is_active == True)
                .first()
            )

            if not user_tariff:
                return {"has_tariff": False, "message": "У вас нет активного тарифа"}

            tariff_plan = (
                session.query(TariffPlan)
                .filter(TariffPlan.id == user_tariff.tariff_plan_id)
                .first()
            )

            if not tariff_plan:
                return {"has_tariff": False, "message": "Тариф не найден"}

            # Получаем количество проектов пользователя
            projects_count = (
                session.query(Project)
                .filter(Project.user_id == user_id, Project.is_active == True)
                .count()
            )

            # Получаем количество чатов во всех проектах пользователя
            chats_count = 0
            for project in (
                session.query(Project).filter(Project.user_id == user_id).all()
            ):
                chats_count += (
                    session.query(ProjectChat)
                    .filter(
                        ProjectChat.project_id == project.id,
                        ProjectChat.is_active == True,
                    )
                    .count()
                )

            return {
                "has_tariff": True,
                "tariff_name": tariff_plan.name,
                "max_projects": tariff_plan.max_projects,
                "max_chats_per_project": tariff_plan.max_chats_per_project,
                "current_projects": projects_count,
                "current_chats": chats_count,
                "end_date": user_tariff.end_date.strftime("%d.%m.%Y"),
                "days_left": (user_tariff.end_date - datetime.now()).days,
            }

    def get_all_active_user_tariffs(self) -> List[UserTariff]:
        """Получает все активные тарифы пользователей"""
        with self.get_session() as session:
            now = datetime.now()
            # Сначала деактивируем все истекшие тарифы
            expired_tariffs = (
                session.query(UserTariff)
                .filter(UserTariff.is_active == True, UserTariff.end_date <= now)
                .all()
            )

            if expired_tariffs:
                for tariff in expired_tariffs:
                    tariff.is_active = False
                session.commit()

            # Затем получаем все активные тарифы
            return session.query(UserTariff).filter(UserTariff.is_active == True).all()

    def __del__(self):
        """Закрываем соединение при удалении объекта"""
        self.engine.dispose()
