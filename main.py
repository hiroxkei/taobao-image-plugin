# -*- coding: utf-8 -*-
"""
Created on Wed Apr 16 20:49:22 2025

@author: 殇璃
"""
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import requests, json, base64, os
from bs4 import BeautifulSoup
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Image Search & Upload API",
    description="Search image from Bing and upload to imgbb",
    version="1.0",
    openapi_version="3.1.0",
    servers=[
        {"url": "https://image-search-plugin.onrender.com"}
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源访问（可以改为指定域名）
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有请求方法：GET、POST、OPTIONS 等
    allow_headers=["*"],  # 允许所有请求头
)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/.well-known/ai-plugin.json", include_in_schema=False)
def plugin_manifest():
    return FileResponse("static/ai-plugin.json")

def is_supported_image_format(content_type):
    """判断图片类型是否支持"""
    return any(fmt in content_type for fmt in ["jpeg", "jpg", "png"])

def search_image_url(query):
    """从淘宝搜索结果中提取第一个商品图片 URL（仅限 jpg/jpeg/png）"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0"
        "Referer": "https://s.taobao.com/",
        "Cookie": os.getenv("TAOBAO_COOKIE")  # 可以直接写死你的 Cookie 字符串
        }

    # 淘宝搜索 URL（搜索结果页）
    search_url = f"https://s.taobao.com/search?q={query}"

    res = requests.get(search_url, headers=headers, timeout=10)
    if res.status_code != 200:
        raise Exception("淘宝搜索页面请求失败")

    soup = BeautifulSoup(res.text, "html.parser")

    # 提取商品图片标签（img 标签）
    img_tags = soup.find_all("img")

    for img in img_tags:
        src = img.get("src") or img.get("data-src") or img.get("data-ks-lazyload")
        if not src:
            continue
        # 有些链接是 //开头的，需要加上 https:
        if src.startswith("//"):
            src = "https:" + src
        if src.startswith("http") and any(ext in src for ext in [".jpg", ".jpeg", ".png"]):
            # HEAD 请求验证链接是否有效
            head_res = requests.head(src, timeout=5)
            content_type = head_res.headers.get("Content-Type", "")
            if head_res.status_code == 200 and is_supported_image_format(content_type):
                return src

    raise Exception("未能从淘宝找到合适的图片（仅限 jpg/jpeg/png）")

def download_image(image_url):
    """下载图片字节内容"""
    res = requests.get(image_url, stream=True, timeout=10)
    content_type = res.headers.get("Content-Type", "")

    if res.status_code == 200 and content_type.startswith("image"):
        if is_supported_image_format(content_type):
            return res.content
        else:
            raise Exception(f"不支持的图片格式：{content_type}")
    raise Exception("图片下载失败或内容格式不对")


def upload_to_imgbb(image_bytes, imgbb_api_key):
    """将图片上传至 imgbb 并返回图片 URL"""
    image_base64 = base64.b64encode(image_bytes).decode("utf-8")
    payload = {
        "key": imgbb_api_key,
        "image": image_base64
    }
    res = requests.post("https://api.imgbb.com/1/upload", data=payload)
    json_data = res.json()
    if res.status_code == 200 and json_data.get("success") == True:
        return json_data["data"]["url"]
    raise Exception("上传失败，请检查响应内容")

@app.get("/get_image_url")
def get_image_url(product: str = Query(..., description="商品或关键词"), imgbb_key: str = Query(None, description="在 imgbb 获取你的 API key")):
    try:
         # 如果请求参数中没有提供 imgbb_key，则从环境变量中读取
        if not imgbb_key:
            imgbb_key = os.getenv("IMGBB_API_KEY")
            if not imgbb_key:
                raise ValueError("未提供 imgbb API 密钥，且环境变量中未设置 IMGBB_API_KEY")
                
        image_url = search_image_url(product)
        image_bytes = download_image(image_url)
        final_url = upload_to_imgbb(image_bytes, imgbb_key)
        return JSONResponse(content={
            "status": "success",
            "product": product,
            "url": final_url,
            "markdown_embed": f"![{product}]({final_url})"
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

from fastapi.openapi.utils import get_openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    # 强制设定 OpenAPI 版本 & servers 字段
    openapi_schema["openapi"] = "3.1.0"
    openapi_schema["servers"] = [
        {"url": "https://image-search-plugin.onrender.com"}
    ]
    # ✅ 补全 get_image_url 的响应结构
    if "/get_image_url" in openapi_schema["paths"]:
        get_op = openapi_schema["paths"]["/get_image_url"]["get"]
        if "responses" in get_op and "200" in get_op["responses"]:
            get_op["responses"]["200"]["content"]["application/json"]["schema"] = {
                "type": "object",
                "properties": {
                    "status": { "type": "string" },
                    "product": { "type": "string" },
                    "url": { "type": "string", "format": "uri" },
                    "markdown_embed": { "type": "string" }
                }
            }
            
    app.openapi_schema = openapi_schema
    return app.openapi_schema

# 应用新的 openapi 定义
app.openapi = custom_openapi
