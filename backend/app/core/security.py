"""安全工具 - 用于加密/解密敏感配置"""
import base64
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


# 从环境变量获取加密密钥，如果没有则生成一个（仅内存中，重启后变化）
# 建议在生产环境设置固定的 ENCRYPTION_KEY
_encryption_key = None


def get_encryption_key() -> bytes:
    """获取或生成加密密钥"""
    global _encryption_key
    if _encryption_key is not None:
        return _encryption_key
    
    # 尝试从环境变量获取
    env_key = os.environ.get("ENCRYPTION_KEY")
    if env_key:
        _encryption_key = env_key.encode()
    else:
        # 生成一个基于机器标识的确定性密钥（重启后相同）
        # 使用固定的 salt 和迭代次数
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"novelflow_fixed_salt_2024",  # 固定 salt
            iterations=100000,
        )
        # 使用机器相关标识或随机值
        machine_id = os.environ.get("MACHINE_ID", "novelflow_default_key")
        _encryption_key = base64.urlsafe_b64encode(kdf.derive(machine_id.encode()))
    
    return _encryption_key


def encrypt_value(value: str) -> str:
    """加密字符串值"""
    if not value:
        return value
    try:
        f = Fernet(get_encryption_key())
        encrypted = f.encrypt(value.encode())
        return base64.urlsafe_b64encode(encrypted).decode()
    except Exception:
        # 加密失败返回原值（避免数据丢失）
        return value


def decrypt_value(encrypted_value: str) -> str:
    """解密字符串值"""
    if not encrypted_value:
        return encrypted_value
    try:
        f = Fernet(get_encryption_key())
        # 先解码 base64
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_value.encode())
        decrypted = f.decrypt(encrypted_bytes)
        return decrypted.decode()
    except Exception:
        # 解密失败返回原值（可能是明文存储的旧数据）
        return encrypted_value
