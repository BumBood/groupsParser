from typing import Optional, List
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from db.models import PaymentHistory, User, Base, ReferralLink


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

    def create_referral_link(self, code: str) -> ReferralLink:
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
            if ref_link:
                return len(ref_link.users)
            return 0

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

    def __del__(self):
        """Закрываем соединение при удалении объекта"""
        self.engine.dispose()
