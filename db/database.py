from typing import Optional, List
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session

from db.models import User, Base, ReferralLink


class Database:
    def __init__(self, db_path: str = "database.db") -> None:
        # Получаем абсолютный путь к файлу БД
        base_dir = os.path.dirname(os.path.abspath(__file__))
        db_url = f"sqlite:///{os.path.join(base_dir, db_path)}"

        # Создаем движок базы данных
        self.engine = create_engine(
            db_url, connect_args={"check_same_thread": False}  # Важно для SQLite
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

    def create_user(self, user_id: int) -> User:
        """Создает нового пользователя"""
        with self.get_session() as session:
            user = User(user_id=user_id)
            session.add(user)
            session.commit()
            session.refresh(user)
            return user

    def get_or_create_user(self, user_id: int) -> User:
        """Получает существующего пользователя или создает нового"""
        is_new = False
        user = self.get_user(user_id)
        if not user:
            user = self.create_user(user_id)
            is_new = True
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

    def create_referral_link(self, code: str, source: str = None) -> ReferralLink:
        """Создает новую реферальную ссылку"""
        with self.get_session() as session:
            ref_link = ReferralLink(code=code, source=source)
            session.add(ref_link)
            session.commit()
            session.refresh(ref_link)
            return ref_link

    def increment_referral_clicks(self, code: str) -> int:
        """Увеличивает счетчик кликов для реферальной ссылки"""
        with self.get_session() as session:
            ref_link = (
                session.query(ReferralLink).filter(ReferralLink.code == code).first()
            )
            if ref_link:
                ref_link.clicks += 1
            session.commit()
            session.refresh(ref_link)
            return ref_link.clicks

    def get_referral_link(self, code: str) -> Optional[ReferralLink]:
        """Получает информацию о реферальной ссылке"""
        with self.get_session() as session:
            return session.query(ReferralLink).filter(ReferralLink.code == code).first()

    def get_or_create_referral_link(
        self, code: str, source: str = None
    ) -> ReferralLink:
        """Получает существующую реферальную ссылку или создает новую"""
        with self.get_session() as session:
            ref_link = (
                session.query(ReferralLink).filter(ReferralLink.code == code).first()
            )
            if ref_link:
                return ref_link

            ref_link = ReferralLink(code=code, source=source)
            session.add(ref_link)
            session.commit()
            session.refresh(ref_link)
            return ref_link

    def get_all_referral_links(self) -> List[ReferralLink]:
        """Получает все реферальные ссылки"""
        with self.get_session() as session:
            return session.query(ReferralLink).all()

    def __del__(self):
        """Закрываем соединение при удалении объекта"""
        self.engine.dispose()
