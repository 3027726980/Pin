"""
生成一个超长有效期的 Access Token（365 天），方便 Apifox 测试。

用法：
    cd D:/MyProject/Pin
    .venv/Scripts/python.exe backend/scripts/create_dev_token.py
"""
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 确保项目根在 import path 中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from backend.core.database import async_session_local
from backend.core.security import _create_token
from backend.repositories import UserRepo, TokenWhitelistRepo


async def main():
    async with async_session_local() as db:
        # 找管理员
        user = await UserRepo.get_by_username(db, "admin")
        if user is None:
            print("❌ 管理员账号不存在，请先启动后端完成种子初始化")
            return

        # 签发一个 365 天的 access token
        access_token, jti = _create_token(
            data={"sub": str(user.id), "type": "access"},
            expires_delta=timedelta(days=365),
        )

        # 写入白名单
        await TokenWhitelistRepo.add_access(
            db,
            user_id=user.id,
            token_jti=jti,
            expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        )
        await db.commit()

        print(f"✅ Token 已生成（有效期 365 天）：\n")
        print(access_token)
        print(f"\n--- 复制上面这行到 Apifox 使用 ---")


if __name__ == "__main__":
    asyncio.run(main())
