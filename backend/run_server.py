#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NovelFlow 直接启动脚本
通过 Python 代码直接启动 FastAPI 应用，不使用命令行调用，方便开发和调试
"""

import sys
from pathlib import Path

import uvicorn

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


def main():
    port = 8000
    """直接启动 FastAPI 应用"""
    print("🎯 NovelFlow 后端服务启动器")
    print("=" * 40)
    print("🚀 正在启动服务...")
    print("🌐 地址: http://localhost:" + str(port))
    print("📚 文档: http://localhost:" + str(port) + "/docs")
    print("🔧 开发模式: 开启")
    print("按 Ctrl+C 停止服务")
    print()

    try:
        # 直接运行 uvicorn
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=port,
            reload=True,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n🛑 服务已停止")
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()