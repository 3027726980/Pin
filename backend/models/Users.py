from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.Base import Base


class Users(Base):
    __tablename__ = "users"
    __table_args__ = {"comment": "用户表：MVP 阶段仅存一个管理员，v0.5 扩展为多租户用户体系"}

    username: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, comment="登录用户名，唯一"
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="bcrypt 哈希密文，不可逆"
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="管理员标识：true=超级管理员，false=普通用户"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="账号启用状态：true=正常，false=禁用"
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username})>"
