# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个基于 Model Context Protocol (MCP) 的服务器,用于从抖音和小红书分享链接中获取无水印视频并提取文本内容。

## 核心架构

### 1. 处理器模式 (Processor Pattern)

项目采用处理器模式,每个平台有独立的处理器类:

- **DouyinProcessor** (`douyin_processor.py`): 处理抖音视频
  - 解析分享链接获取视频 ID 和无水印 URL
  - 使用阿里云百炼 API (dashscope) 进行语音识别
  - 直接从视频 URL 进行转录(无需下载)

- **XiaohongshuProcessor** (`xiaohongshu_processor.py`): 处理小红书视频
  - 解析 HTML 页面提取视频直链
  - 启发式评分算法选择无水印版本(优先 114 质量码)
  - 域名规范化和 HEAD 探测验证

### 2. MCP 服务器 (`server.py`)

使用 FastMCP 框架提供统一的 MCP 接口:

**工具 (Tools):**
- `parse_douyin_link`: 解析抖音链接，自动识别视频/图文并返回无水印资源(无需 API 密钥)
- `parse_xhs_link`: 解析小红书链接，自动识别视频/图文并返回无水印资源(无需 API 密钥)
- `extract_douyin_text`: 从抖音视频中提取文本内容(需要 API 密钥)

资源接口已在当前版本移除，统一通过上述工具完成解析。

**提示词 (Prompts):**
- `douyin_text_extraction_guide`: 使用指南

### 3. 关键技术实现

**视频 URL 解析:**
- 抖音: 通过 `window._ROUTER_DATA` 提取 JSON 数据,替换 `playwm` 为 `play` 去水印
- 小红书: 多重策略(video 标签、og:video meta、正则回退),启发式评分选择最优链接

**文本提取:**
- 使用 dashscope.audio.asr.Transcription 异步 API
- 直接传入视频 URL,无需本地下载
- 默认模型: `paraformer-v2`

## 常用命令

### 本地开发测试

```bash
# 启动 MCP 服务器(需要设置 DASHSCOPE_API_KEY 环境变量)
python -m douyin_mcp_server

# 测试抖音链接解析(无需 API 密钥)
python -m douyin_mcp_server.douyin_processor "<抖音分享链接>"

# 测试小红书链接解析(无需 API 密钥)
python -m douyin_mcp_server.xiaohongshu_processor "<小红书分享链接>"
```

### 安装依赖

```bash
# 开发模式安装
pip install -e .

# 使用 uv 运行(生产环境)
uvx douyin-mcp-server
```

### Claude Desktop 本地开发配置

```json
{
  "mcpServers": {
    "douyin-mcp": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/douyin-mcp-server",
        "python",
        "-m",
        "douyin_mcp_server"
      ],
      "env": {
        "DASHSCOPE_API_KEY": "your-api-key-here"
      }
    }
  }
}
```

## 环境变量

- `DASHSCOPE_API_KEY`: 阿里云百炼 API 密钥(文本提取功能必需)
  - 获取地址: https://help.aliyun.com/zh/model-studio/get-api-key

## 重要注意事项

### 模块化设计
- 避免在包初始化时导入重量级依赖(如 ffmpeg)
- 支持独立运行各处理器模块进行测试

### API 密钥使用
- 获取下载链接功能无需 API 密钥
- 文本提取功能需要有效的 DASHSCOPE_API_KEY
- API 密钥通过环境变量传入,不硬编码

### 文件名处理
- 使用正则表达式清理非法文件名字符: `r'[\\/:*?"<>|]'`
- 避免文件名过长导致的错误

### 临时文件管理
- DouyinProcessor 使用 tempfile.mkdtemp() 创建临时目录
- 在 `__del__` 方法中自动清理临时文件
- 捕获 ImportError 避免 Python 关闭时的清理错误

### 请求头配置
- 抖音使用移动端 UA (iPhone iOS 17_2)
- 小红书优先使用桌面端 UA (Windows Chrome),失败时回退到移动端

## 代码结构设计原则

1. **职责分离**: 处理器类专注于平台特定逻辑,MCP 服务器负责协议适配
2. **错误处理**: 所有异常向上抛出,由 MCP 工具层统一处理并返回 JSON 格式
3. **异步支持**: 下载操作使用异步接口,支持进度报告 (ctx.report_progress)
4. **灵活配置**: 通过构造函数参数和环境变量配置,避免硬编码
