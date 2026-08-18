"""
Mify API 调用层 — HTTP/SQL/飞书 通知
v3: urllib 全链路，零子进程。含飞书卡片直发。
"""

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

# 可选：直接 SQL 查询（绕过 mify SQL workflow）
try:
    import pymysql
    HAS_PYMYSQL = True
except ImportError:
    HAS_PYMYSQL = False

# 全局 SSL context（复用，避免每次握手）
_SSL_CTX = ssl.create_default_context()


class MifyClient:
    """通过 mify API 调用 HTTP / SQL"""

    def __init__(self, endpoint: str, token: str, user: str = "ou_0f523a90cdfbb1cc84ccf67ba3fcf7ef",
                 sql_workflow_id: str = "", http_workflow_id: str = "",
                 sql_token: str = ""):
        self.endpoint = endpoint
        self.token = token
        self.sql_token = sql_token or token
        self.user = user
        self.sql_workflow_id = sql_workflow_id
        self.http_workflow_id = http_workflow_id

    # ── 底层 HTTP ──────────────────────────────────────────────

    def _request(self, url: str, method: str = "GET",
                 data: bytes = None, headers: dict = None,
                 timeout: int = 120) -> urllib.response.addinfourl:
        """统一 urllib 请求，自动处理 SSL / 超时 / 重定向"""
        req = urllib.request.Request(url, data=data, method=method.upper())
        req.add_header('User-Agent', 'datamaker-engine/4.1')
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        return urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX)

    # ── mify streaming 调用 ────────────────────────────────────

    def _post(self, payload: dict, timeout: int = 90, token: str = "") -> dict:
        """通用 mify streaming 调用（SSE 逐行读取）"""
        use_token = token or self.token
        body = json.dumps(payload).encode()

        t0 = time.time()
        # ── 429 限流退避重试 ──
        # mify 端在短时间高频调用（如连续多次 approve_pr / pr_to_po）会返回 HTTP 429。
        # 这是瞬时限流，非业务错误：指数退避重试（2s/5s/10s），最多 3 次。
        max_retries = 3
        backoffs = [2, 5, 10]
        resp = None
        for attempt in range(max_retries + 1):
            try:
                resp = self._request(
                    self.endpoint, method="POST", data=body,
                    headers={
                        "Authorization": f"Bearer {use_token}",
                        "Content-Type": "application/json",
                    },
                    timeout=timeout + 60,
                )
                break  # 成功拿到响应流
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < max_retries:
                    wait = backoffs[attempt]
                    print(f"  ⏳ HTTP 429 限流，第 {attempt+1} 次退避 {wait}s 后重试...", flush=True)
                    time.sleep(wait)
                    continue
                elapsed = time.time() - t0
                print(f"  ❌ _post 请求失败 ({elapsed:.1f}s): {type(e).__name__}: {e}")
                return {"status": "error", "outputs": {}, "error": str(e)}
            except Exception as e:
                elapsed = time.time() - t0
                print(f"  ❌ _post 请求失败 ({elapsed:.1f}s): {type(e).__name__}: {e}")
                return {"status": "error", "outputs": {}, "error": str(e)}
        if resp is None:
            return {"status": "error", "outputs": {}, "error": "HTTP 429 限流重试耗尽"}

        # 逐行读 SSE（带总超时保护）
        line_count = 0
        last_event = None
        sse_deadline = t0 + timeout + 120  # SSE 读取总超时 = 初始 timeout + 120s 缓冲
        try:
            print(f"  📡 _post: 开始读 SSE ({time.time()-t0:.1f}s)", flush=True)
            # 设置底层 socket 超时，防止 read 永久阻塞
            try:
                resp.fp.raw._sock.settimeout(30)
            except (AttributeError, OSError):
                pass  # 响应已关闭或 socket 不可用
            for raw_line in resp:
                if time.time() > sse_deadline:
                    print(f"  ⏰ _post: SSE 读取超时 ({timeout+120}s)")
                    break
                line = raw_line.decode().strip()
                if not line.startswith("data: "):
                    continue
                line_count += 1
                try:
                    evt = json.loads(line[6:])
                    last_event = evt
                    if evt.get("event") == "workflow_finished":
                        elapsed = time.time() - t0
                        print(f"  ⏱️ mify 返回 ({elapsed:.1f}s), SSE lines: {line_count}")
                        return evt.get("data", {})
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception as e:
            print(f"  ❌ _post SSE 读取异常: {type(e).__name__}: {e}")

        elapsed = time.time() - t0
        print(f"  ⚠️ _post: 未找到 workflow_finished ({elapsed:.1f}s), lines: {line_count}")
        return {"status": "error", "outputs": {}, "error": "mify 无返回"}

    # ── HTTP 接口调用 ──────────────────────────────────────────

    def http_call(self, url: str, method: str = "GET",
                  body: str = "", cookie: str = "",
                  headers: dict = None,
                  timeout: int = 120) -> dict:
        """通过 mify 工作流调用 HTTP 接口

        如果 mify 返回失败，自动回退到 urllib 直接调用。
        """
        input_dict = {
            "url": url,
            "method": method.lower(),
            "body": body,
            "cookie": cookie,
        }
        if headers:
            if isinstance(headers, dict):
                input_dict["headers"] = "\n".join(f"{k}: {v}" for k, v in headers.items())
            elif isinstance(headers, str):
                input_dict["headers"] = headers

        payload = {
            "inputs": input_dict,
            "user": self.user,
            "response_mode": "streaming",
        }
        if self.http_workflow_id:
            payload["workflow_id"] = self.http_workflow_id

        data = self._post(payload, timeout)
        outputs = data.get("outputs", {})
        body_str = outputs.get("body", "")
        status = outputs.get("status_code", 0)
        error_msg = data.get("error", "")

        # 检测 CAS 登录页（SCM 认证失败返回 HTML）
        def _is_cas_page(b: str) -> bool:
            return bool(b) and ('<title>' in b[:500] or 'Central Authentication' in b[:500])

        # mify 完全失败（无响应）→ urllib 直调
        # 注意：如果 mify 返回了任何响应（哪怕是错误），不再 fallback 到直连
        # 因为本机不通 SCM 内网，直连必然挂死
        if status == 0 and not body_str and not error_msg:
            print(f"  ⚠️ mify 无响应，回退到 urllib 直调")
            return self._http_direct(url, method, body, cookie, headers, timeout)

        # mify 返回了 CAS 登录页 → cookie 无效，不 fallback
        if _is_cas_page(body_str):
            print(f"  ❌ SCM 返回 CAS 登录页（cookie 无效或过期），不回退直连")
            return {
                "status_code": status,
                "body": {
                    "_error": "SCM 返回 CAS 登录页，cookie 无效或过期",
                    "_hint": "请检查 cookie 是否正确传递到 mify workflow 的 inputs.cookie 字段",
                    "_status": status,
                }
            }

        # mify HTTP 节点对非 2xx 不抓 body（平台限制）
        if status >= 400 and not body_str:
            print(f"  ⚠️ mify HTTP 节点未捕获 {status} 响应体（平台限制）")
            return {
                "status_code": status,
                "body": {
                    "_error": f"HTTP {status} 响应体被 mify 丢弃（平台限制）",
                    "_hint": "请在 mify 平台检查 HTTP 请求节点的异常处理配置",
                    "_status": status,
                }
            }

        # mify 返回了错误信息 → 不 fallback 直连
        if error_msg and ("tool" in error_msg.lower() or "retries" in error_msg.lower()):
            print(f"  ⚠️ mify 调用出错: {error_msg[:100]}")
            return {
                "status_code": status or 502,
                "body": {
                    "_error": f"mify 调用失败: {error_msg[:200]}",
                    "_status": status,
                }
            }

        try:
            parsed_body = json.loads(body_str)
        except (json.JSONDecodeError, TypeError):
            parsed_body = {"_raw": body_str[:1000]}

        return {"status_code": status, "body": parsed_body}

    def _http_direct(self, url: str, method: str, body: str,
                     cookie: str, headers: dict, timeout: int) -> dict:
        """urllib 直接调用目标接口（fallback）"""
        req_headers = {}
        if cookie and "getSCMCookie" not in url:
            req_headers["Cookie"] = cookie
        if headers:
            req_headers.update(headers)
        if body and method.upper() in ("POST", "PUT", "PATCH"):
            req_headers.setdefault("Content-Type", "application/json")

        data = body.encode() if body else None
        try:
            resp = self._request(url, method=method, data=data,
                                 headers=req_headers, timeout=timeout + 30)
            output = resp.read().decode()
            try:
                parsed_body = json.loads(output)
            except (json.JSONDecodeError, TypeError):
                parsed_body = {"_raw": output[:2000]}
            return {"status_code": resp.status, "body": parsed_body}
        except urllib.error.HTTPError as e:
            output = e.read().decode() if e.fp else ""
            try:
                parsed_body = json.loads(output)
            except:
                parsed_body = {"_raw": output[:2000]}
            return {"status_code": e.code, "body": parsed_body}
        except Exception as e:
            return {"status_code": 500, "body": {"_error": str(e)}}

    # ── SQL 查询 ───────────────────────────────────────────────

    def sql_query(self, db_uri: str, query: str, timeout: int = 60) -> dict:
        """执行 SQL 查询，优先 mify SQL 工作流，回退 pymysql 直连"""
        query = query.strip()
        if not query:
            return {"rows": [], "_error": "空查询"}

        if self.sql_token:
            return self._sql_via_mify(db_uri, query, timeout)

        if HAS_PYMYSQL and db_uri:
            return self._sql_direct(db_uri, query, timeout)

        return {"rows": [], "_error": "无可用 SQL 执行方式（需 sql_token 或 pymysql）"}

    def _sql_via_mify(self, db_uri: str, query: str, timeout: int = 30) -> dict:
        """通过 mify SQL 工作流执行查询（blocking 模式）"""
        payload = {
            "inputs": {"db_uri": db_uri, "query": query},
            "user": self.user,
            "response_mode": "blocking",
        }
        if self.sql_workflow_id:
            payload["workflow_id"] = self.sql_workflow_id

        body = json.dumps(payload).encode()
        try:
            resp = self._request(
                self.endpoint, method="POST", data=body,
                headers={
                    "Authorization": f"Bearer {self.sql_token}",
                    "Content-Type": "application/json",
                },
                timeout=timeout + 15,
            )
            data = json.loads(resp.read().decode())
        except Exception as e:
            return {"rows": [], "_error": f"mify SQL blocking 调用失败: {e}"}

        if data.get("status") == "failed" or data.get("status") == 400:
            return {"rows": [], "_error": data.get("error", "未知错误")}

        outputs = data.get("data", {}).get("outputs", {})
        rows_raw = outputs.get("rows", [])

        rows = []
        for item in rows_raw:
            if isinstance(item, dict) and "result" in item:
                rows.extend(item["result"])
            elif isinstance(item, dict):
                rows.append(item)

        return {"rows": rows, "_raw": ""}

    def _sql_direct(self, db_uri: str, query: str, timeout: int = 60) -> dict:
        """通过 pymysql 直接查询"""
        try:
            uri = db_uri
            if "://" in uri:
                uri = uri.split("://", 1)[1]
            parsed = urllib.parse.urlparse(f"//{uri}")
            host = parsed.hostname
            port = parsed.port or 3306
            user = parsed.username
            password = parsed.password
            database = parsed.path.lstrip("/")
        except Exception as e:
            return {"rows": [], "_error": f"db_uri 解析失败: {e}"}

        try:
            conn = pymysql.connect(
                host=host, port=port, user=user, password=password,
                database=database, charset="utf8mb4",
                connect_timeout=timeout, read_timeout=timeout,
            )
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            cursor.execute(query)

            if query.strip().upper().startswith("SELECT"):
                rows = cursor.fetchall()
                for row in rows:
                    for k, v in row.items():
                        if hasattr(v, 'isoformat'):
                            row[k] = v.isoformat()
                cursor.close()
                conn.close()
                return {"rows": list(rows), "_raw": ""}
            else:
                conn.commit()
                affected = cursor.rowcount
                cursor.close()
                conn.close()
                return {"rows": [], "_raw": f"affected: {affected}"}

        except Exception as e:
            return {"rows": [], "_error": f"SQL执行失败: {e}"}

    # ── Cookie ─────────────────────────────────────────────────

    def get_cookie(self, cookie_url: str) -> str:
        """获取 SCM Cookie"""
        # 方案1：urllib 直接调用
        try:
            resp = self._request(cookie_url, method="GET", timeout=10)
            output = resp.read().decode()
            data = json.loads(output)
            cookie = data.get("data", {}).get("result", {}).get("cookie", "")
            if cookie:
                print(f"  📌 cookie = {cookie[:50]}...")
                return cookie
        except Exception as e:
            print(f"  ⚠️ urllib 获取 Cookie 失败: {e}")

        # 方案2：回退到 mify HTTP workflow
        resp = self.http_call(cookie_url, "get")
        cookie = resp.get("body", {}).get("data", {}).get("result", {}).get("cookie", "")
        return cookie

    # ── 飞书通知（零子进程）────────────────────────────────────

    _feishu_token_cache = {"token": "", "expires": 0}

    def _get_feishu_tenant_token(self) -> str:
        """获取飞书 tenant_access_token（带缓存）"""
        now = time.time()
        if self._feishu_token_cache["token"] and now < self._feishu_token_cache["expires"]:
            return self._feishu_token_cache["token"]

        app_id = os.environ.get("FEISHU_APP_ID", "")
        app_secret = os.environ.get("FEISHU_APP_SECRET", "")
        if not app_id or not app_secret:
            return ""

        try:
            body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
            resp = self._request(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                method="POST", data=body,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            data = json.loads(resp.read().decode())
            token = data.get("tenant_access_token", "")
            expire = data.get("expire", 7200)
            if token:
                self._feishu_token_cache["token"] = token
                self._feishu_token_cache["expires"] = now + expire - 300  # 提前5分钟刷新
                return token
        except Exception:
            pass
        return ""

    def send_feishu_card(self, chat_id: str, title: str, content: str,
                         color: str = "blue") -> bool:
        """发送飞书互动卡片（urllib 直调，零子进程）"""
        token = self._get_feishu_tenant_token()
        if not token:
            return False

        color_map = {
            "blue": "blue", "green": "green", "red": "red",
            "orange": "orange", "purple": "purple",
        }
        template = color_map.get(color, "blue")

        card = {
            "header": {
                "template": template,
                "title": {"tag": "plain_text", "content": title}
            },
            "elements": [
                {"tag": "markdown", "content": content}
            ]
        }

        body = json.dumps({
            "receive_id": chat_id.replace("user:", ""),
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }, ensure_ascii=False).encode()

        try:
            resp = self._request(
                f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
                method="POST", data=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                timeout=10,
            )
            result = json.loads(resp.read().decode())
            return result.get("code", -1) == 0
        except Exception:
            return False
