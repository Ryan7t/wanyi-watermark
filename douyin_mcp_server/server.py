#!/usr/bin/env python3
"""
百分百一键去水印 - MCP 服务器

该服务器为"百分百一键去水印"小程序提供媒体资源解析与提取服务：
1. 智能解析抖音/小红书分享链接，自动识别内容类型（视频/图文）
2. 提取无水印视频直链，支持高清画质下载
3. 提取无水印图片资源，支持多格式输出（WebP/PNG）
4. 视频文本转写功能，从视频中提取语音内容（基于阿里云百炼API）
5. 通用平台兜底机制，支持未适配平台的链接解析
"""

import os
import re
import json
import requests
import tempfile
import asyncio
from pathlib import Path
from typing import Optional, Tuple
import ffmpeg
from tqdm.asyncio import tqdm
from urllib import request
from http import HTTPStatus
import dashscope

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Context

from .xiaohongshu_processor import XiaohongshuProcessor
from .douyin_processor import DouyinProcessor
from .generic_extractor import extract_generic_media

# 创建 MCP 服务器实例
mcp = FastMCP("百分百一键去水印",
              dependencies=["requests", "ffmpeg-python", "tqdm", "dashscope"])

# 请求头，模拟移动端访问
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 Version/17.0 Mobile/15E148 Safari/604.1'
}

# 默认 API 配置
DEFAULT_MODEL = "paraformer-v2"


def _generic_fallback(share_link: str, reason: str) -> str:
    """通用兜底逻辑：在专用解析失败时尝试通用提取。"""

    try:
        fallback_data = extract_generic_media(share_link)
        fallback_data.setdefault("fallback_reason", reason)
        return json.dumps(fallback_data, ensure_ascii=False, indent=2)
    except Exception as fallback_error:
        return json.dumps({
            "status": "error",
            "error": f"{reason}；兜底解析失败：{fallback_error}"
        }, ensure_ascii=False, indent=2)

@mcp.tool()
def parse_xhs_link(share_link: str) -> str:
    """
    解析小红书分享链接，自动识别视频或图文类型并返回无水印资源

    参数:
    - share_link: 小红书分享链接或包含链接的文本

    返回:
    - 包含资源链接和信息的JSON字符串
    - 自动识别类型（video/image）并返回相应格式
    - 调用完成后，请将结果整理为以下纯文本格式并反馈给用户（禁止使用Markdown）：
      标题（如无则留空）：
      文案：
      视频/图片链接：
    - 返回时请保留完整的标题和文案，不要省略或截断任何内容
    - 若专用解析失败，将自动尝试 generic 兜底逻辑；调用方需同样按上述格式反馈结果
    - 抖音仅返回 caption 字段，标题需由调用方自行按需补充
    """
    try:
        processor = XiaohongshuProcessor()

        # 先尝试解析视频
        try:
            video_info = processor.parse_share_url(share_link)
            return json.dumps({
                "status": "success",
                "type": "video",
                "platform": "xiaohongshu",
                "note_id": video_info.get("note_id", ""),
                "title": video_info["title"],
                "caption": video_info.get("desc", ""),
                "url": video_info["url"],
                "description": f"视频标题: {video_info['title']}"
            }, ensure_ascii=False, indent=2)
        except Exception as video_error:
            # 如果视频解析失败，尝试图文解析
            error_msg = str(video_error).lower()
            if "未从页面中发现可用视频直链" in error_msg or "video" in error_msg or "候选" in error_msg:
                try:
                    note_data = processor.parse_image_note(share_link)
                    return json.dumps({
                        "status": "success",
                        "type": "image",
                        "platform": "xiaohongshu",
                        "note_id": note_data["note_id"],
                        "title": note_data["title"],
                        "desc": note_data["desc"],
                        "caption": note_data.get("desc", ""),
                        "image_count": len(note_data["images"]),
                        "images": note_data["images"],
                        "format_info": {
                            "webp": "轻量格式，体积小（约160KB），适合快速预览和节省带宽",
                            "png": "无损格式，高质量（约1.8MB），支持透明背景，适合编辑和打印"
                        }
                    }, ensure_ascii=False, indent=2)
                except Exception as image_error:
                    return _generic_fallback(share_link, f"小红书图文解析失败: {image_error}")
            return _generic_fallback(share_link, f"小红书视频解析失败: {video_error}")

    except Exception as e:
        return _generic_fallback(share_link, f"解析小红书链接失败: {e}")

@mcp.tool()
async def extract_douyin_text(
    share_link: str,
    model: Optional[str] = None,
    ctx: Context = None
) -> str:
    """
    从抖音分享链接提取视频中的文本内容

    参数:
    - share_link: 抖音分享链接或包含链接的文本
    - model: 语音识别模型（可选，默认使用paraformer-v2）

    返回:
    - 提取的文本内容

    注意: 需要设置环境变量 DASHSCOPE_API_KEY
    """
    try:
        # 从环境变量获取API密钥
        api_key = os.getenv('DASHSCOPE_API_KEY')
        if not api_key:
            raise ValueError("未设置环境变量 DASHSCOPE_API_KEY，请在配置中添加阿里云百炼API密钥")

        processor = DouyinProcessor(api_key, model)

        # 解析视频链接
        ctx.info("正在解析抖音分享链接...")
        video_info = processor.parse_share_url(share_link)

        # 直接使用视频URL进行文本提取
        ctx.info("正在从视频中提取文本...")
        text_content = processor.extract_text_from_video_url(video_info['url'])

        ctx.info("文本提取完成!")
        return text_content

    except Exception as e:
        ctx.error(f"处理过程中出现错误: {str(e)}")
        raise Exception(f"提取抖音视频文本失败: {str(e)}")

# 注意：当前阶段仅在内部开发使用，尚无客户端依赖旧工具名，因此只保留统一的 parse_* 接口。
# 若后续对外发布或有现网依赖，请考虑恢复旧名称的兼容包装以避免破坏现有集成。
@mcp.tool()
def parse_douyin_link(share_link: str) -> str:
    """
    解析抖音分享链接，自动识别视频或图文类型并返回无水印资源

    参数:
    - share_link: 抖音分享链接或包含链接的文本

    返回:
    - 包含资源链接和信息的JSON字符串
    - 自动识别类型（video/image）并返回相应格式
    - 调用完成后，请将结果整理为以下纯文本格式并反馈给用户（禁止使用Markdown）：
      标题（如无则留空）：
      文案：
      视频/图片链接：
    - 返回时请保留完整的标题和文案，不要省略或截断任何内容
    - 若专用解析失败，将自动尝试 generic 兜底逻辑；调用方需同样按上述格式反馈结果
    - 抖音仅返回 caption 字段，标题需由调用方自行按需补充
    """
    try:
        processor = DouyinProcessor("")  # 获取资源不需要API密钥

        # 先尝试解析视频
        try:
            video_info = processor.parse_share_url(share_link)
            # 仅输出 caption 和资源链接，前端已确认无需 title 字段
            return json.dumps({
                "status": "success",
                "type": "video",
                "platform": "douyin",
                "video_id": video_info["video_id"],
                "caption": video_info.get("caption", ""),
                "url": video_info["url"]
            }, ensure_ascii=False, indent=2)
        except Exception as video_error:
            # 如果视频解析失败，检查是否为图文笔记
            error_msg = str(video_error)
            if "这是图文笔记" in error_msg:
                try:
                    note_data = processor.parse_image_note(share_link)
                    # 图文同样只保留 caption，避免重复字段
                    return json.dumps({
                        "status": "success",
                        "type": "image",
                        "platform": "douyin",
                        "note_id": note_data["note_id"],
                        "caption": note_data.get("caption", ""),
                        "image_count": len(note_data["images"]),
                        "images": note_data["images"]
                    }, ensure_ascii=False, indent=2)
                except Exception as image_error:
                    return _generic_fallback(share_link, f"抖音图文解析失败: {image_error}")
            return _generic_fallback(share_link, f"抖音视频解析失败: {video_error}")

    except Exception as e:
        return _generic_fallback(share_link, f"解析抖音链接失败: {e}")


@mcp.tool()
def parse_generic_link(share_link: str) -> str:
    """解析任意短视频/图文链接，直接启用 generic 兜底逻辑。

    参数:
    - share_link: 任意平台的分享链接或包含链接的文本（抖音/小红书亦可传入）

    返回:
    - 包含资源链接和信息的JSON字符串
    - 输出字段与其它工具一致：platform/title/caption/url
    - 调用完成后，请将结果整理为以下纯文本格式并反馈给用户（禁止使用Markdown）：
      标题（如无则留空）：
      文案：
      视频/图片链接：
    - 请完整保留标题与文案的全部内容，不要省略或截断
    - 若未能解析，将返回错误说明（可能原因：页面无直链、需要登录等）
    """
    try:
        result = extract_generic_media(share_link)
        result.setdefault("fallback_reason", "generic_tool_invocation")
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({
            "status": "error",
            "error": f"通用解析失败: {e}"
        }, ensure_ascii=False, indent=2)

@mcp.prompt()
def watermark_removal_guide() -> str:
    """百分百一键去水印使用指南 - 视频链接解析与媒体资源提取"""
    return """
# 百分百一键去水印 - MCP 服务使用指南

## 功能概述
本 MCP 服务器为"百分百一键去水印"小程序提供核心技术支持，实现多平台视频/图片链接的智能解析与媒体资源提取。

### 核心能力
- 🔗 智能链接解析：自动识别抖音/小红书分享链接，解析真实视频地址
- 📹 无水印视频提取：获取高清无水印视频直链，支持直接下载
- 🖼️ 图片资源提取：支持图文笔记解析，提供多格式图片（WebP轻量/PNG高清）
- 📝 视频文本转写：基于AI语音识别，从视频中提取文字内容
- 🌐 通用平台兜底：遇到未适配平台时，自动尝试通用解析机制

## 环境变量配置
视频文本转写功能需要设置以下环境变量：
- `DASHSCOPE_API_KEY`: 阿里云百炼API密钥（仅文本转写功能需要，链接解析无需密钥）

## 使用步骤
1. 复制抖音/小红书的分享链接（或包含链接的文本）
2. 使用相应的工具进行解析
3. 对于文本转写功能，需在 Claude Desktop 配置中设置环境变量

## 工具说明

### 主要工具（自动识别类型）
- `parse_douyin_link`: 解析抖音链接，自动识别视频/图文并返回无水印资源，失败时自动尝试通用解析
- `parse_xhs_link`: 解析小红书链接，自动识别视频/图文并返回无水印资源，失败时自动尝试通用解析

### 兜底工具
- `parse_generic_link`: 通用平台链接解析，适用于未明确支持的平台或作为备用方案

### 特殊功能
- `extract_douyin_text`: 从抖音视频中提取语音文本内容（需要 API 密钥）

## Claude Desktop 配置示例
```json
{
  "mcpServers": {
    "douyin-mcp": {
      "command": "uvx",
      "args": ["douyin-mcp-server"],
      "env": {
        "DASHSCOPE_API_KEY": "your-dashscope-api-key-here"
      }
    }
  }
}
```

## 返回格式

### 统一输出要求（禁止使用任何Markdown语法）
在工具执行结束后，请按下面的顺序组织最终回复：
标题（如无则留空）：<可选的简短标题>
文案：<完整文案或说明，抖音等平台可直接使用唯一的文本内容>
视频/图片链接：<逐项列出所有资源链接，多个链接可分行>
请完整保留标题与文案的全部内容，不要省略或截断。
如果获得的是通用解析结果（platform=generic），标题可能来自网页 og:title，文案可能为空，也请按格式显式告知。

## 技术特点
- ✅ 链接解析无需密钥：视频/图片资源提取完全免费，无需任何 API 配置
- ✅ 智能类型识别：自动判断内容类型（视频/图文），无需手动指定
- ✅ 多格式支持：小红书图文提供 WebP（快速预览）和 PNG（高清编辑）双格式
- ✅ 高精度文本转写：使用阿里云百炼 paraformer-v2 模型，识别准确率高
- ✅ 多平台兼容：支持抖音、小红书，并提供通用解析兜底机制
"""

def main():
    """启动MCP服务器"""
    mcp.run()

if __name__ == "__main__":
    main()
