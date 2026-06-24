"""
Mify API 调用层 — HTTP/SQL 执行
从 engine.py 原封不动提取，保证向后兼容。
"""

import json
import subprocess
from typing import Optional

# 可选：直接 SQL 查询（绕过 mify SQL workflow）
try:
    import pymysql
    HAS_PYMYSQL = True
except ImportError:
    HAS_PYMYSQL = False


class MifyClient:
    """通过 mify API 调用 HTTP / SQL"""

    def __init__(self, endpoint: str, token: str, user: str = "skill-runner",
                 sql_workflow_id: str = "", http_workflow_id: str = "",
                 sql_token: str = ""):
        self.endpoint = endpoint
        self.token = token
        self.sql_token = sql_token or token  # SQL 可能用不同的 token
        self.user = user
        self.sql_workflow_id = sql_workflow_id
        self.http_workflow_id = http_workflow_id

    def _post(self, payload: dict, timeout: int = 90, token: str = "") -> dict:
        """通用 mify streaming 调用"""
        use_token = token or self.token
        cmd = [
            "curl", "-s", "-X", "POST", self.endpoint,
            "-H", f"Authorization: Bearer {use_token}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload),
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout + 30
            )
            output = result.stdout
            print(f"  🔍 curl output length: {len(output)}")
            print(f"  🔍 curl output first 500 chars: {output[:500]}")

            for line in output.strip().split("\n"):
                if line.startswith("data: "):
                    try:
                        evt = json.loads(line[6:])
                        if evt["event"] == "workflow_finished":
                            return evt["data"]
                    except (json.JSONDecodeError, KeyError):
                        continue

            return {"status": "error", "outputs": {}, "error": "mify 无返回"}
        except Exception as e:
            return {"status": "error", "outputs": {}, "error": str(e)}

    def http_call(self, url: str, method: str = "GET",
                  body: str = "", cookie: str = "",
                  headers: dict = None,
                  timeout: int = 60) -> dict:
        """通过 mify 工作流调用 HTTP 接口

        如果 mify 返回失败（如工具站不可达），自动回退到 curl 直接调用。
        """
        input_dict = {
                "url": url,
                "method": method.lower(),
                "body": body,
                "cookie": cookie,
            }
        # mify HTTP 工作流 headers 需要字符串格式 "Key: Value\nKey2: Value2"
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

        # 如果 mify 调用失败（空响应或错误），自动回退到 curl
        if status == 0 or "Reached maximum retries" in error_msg or "tool" in error_msg.lower():
            print(f"  ⚠️ mify 调用失败 (status={status}, error={error_msg[:80]})，回退到 curl 直调")
            try:
                cmd = ["curl", "-s", "-X", method.upper(), url]
                # Cookie 获取接口通常不需要带 Cookie，其他接口按配置传入。
                if cookie and "getSCMCookie" not in url:
                    cmd.extend(["-H", f"Cookie: {cookie}"])
                if headers:
                    for k, v in headers.items():
                        cmd.extend(["-H", f"{k}: {v}"])
                if body and method.upper() in ("POST", "PUT", "PATCH"):
                    cmd.extend(["-H", "Content-Type: application/json"])
                    cmd.extend(["-d", body])
                cmd.extend(["--connect-timeout", str(timeout)])
                cmd.extend(["--max-time", str(timeout + 10)])
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 15)
                output = result.stdout
                try:
                    parsed_body = json.loads(output)
                except (json.JSONDecodeError, TypeError):
                    parsed_body = {"_raw": output[:2000]}
                status = 200 if result.returncode == 0 else 500
                return {"status_code": status, "body": parsed_body}
            except Exception as e:
                return {"status_code": 500, "body": {"_error": str(e)}}

        try:
            parsed_body = json.loads(body_str)
        except (json.JSONDecodeError, TypeError):
            parsed_body = {"_raw": body_str[:1000]}
        # DEBUG: 如果 body_str 看起来像 JSON 但解析后没有 code 字段，打印一下
        if isinstance(parsed_body, dict) and "code" not in parsed_body and "body" not in parsed_body and len(body_str) > 50:
            print(f"  🔍 DEBUG http_call response: parsed_body keys={list(parsed_body.keys())}, body_str preview={body_str[:200]}")
        return {"status_code": status, "body": parsed_body}

    def sql_query(self, db_uri: str, query: str, timeout: int = 60) -> dict:
        """执行 SQL 查询，优先 mify SQL 工作流，回退 pymysql 直连"""
        query = query.strip()
        if not query:
            return {"rows": [], "_error": "空查询"}

        # 方案1：mify SQL workflow（推荐，走内网访问数据库）
        if self.sql_token:
            return self._sql_via_mify(db_uri, query, timeout)

        # 方案2：pymysql 直连（如果数据库可达）
        if HAS_PYMYSQL and db_uri:
            return self._sql_direct(db_uri, query, timeout)

        return {"rows": [], "_error": "无可用 SQL 执行方式（需 sql_token 或 pymysql）"}

    def _sql_direct(self, db_uri: str, query: str, timeout: int = 60) -> dict:
        """通过 pymysql 直接查询"""
        import urllib.parse

        # 解析 db_uri，例如 ${SCM_DB_URI}
        try:
            # 去掉 mysql+pymysql:// 前缀
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
                # datetime 等类型转字符串
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

    def _sql_via_mify(self, db_uri: str, query: str, timeout: int = 30) -> dict:
        """通过 mify SQL 工作流执行查询（blocking 模式，~15s vs streaming ~60s）

        注意：blocking 模式的 input key 必须是 db_uri（下划线），不是 dbUri。
        """
        payload = {
            "inputs": {
                "db_uri": db_uri,
                "query": query,
            },
            "user": self.user,
            "response_mode": "blocking",
        }

        # SQL workflow 用独立的 token，传 sql_workflow_id 作为 workflow_id
        if self.sql_workflow_id:
            payload["workflow_id"] = self.sql_workflow_id

        cmd = [
            "curl", "-s", "-X", "POST", self.endpoint,
            "-H", f"Authorization: Bearer {self.sql_token}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload),
            "--max-time", str(timeout),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout + 30
            )
            output = result.stdout
            data = json.loads(output)
        except Exception as e:
            return {"rows": [], "_error": f"mify SQL blocking 调用失败: {e}"}

        if data.get("status") == "failed" or data.get("status") == 400:
            error = data.get("error", "未知错误")
            return {"rows": [], "_error": error}

        # blocking 模式返回结构为 data.outputs（比 streaming 多一层 data 包裹）
        outputs = data.get("data", {}).get("outputs", {})
        rows_raw = outputs.get("rows", [])

        rows = []
        for item in rows_raw:
            if isinstance(item, dict) and "result" in item:
                rows.extend(item["result"])
            elif isinstance(item, dict):
                rows.append(item)

        return {"rows": rows, "_raw": ""}

    def get_cookie(self, cookie_url: str) -> str:
        """获取 SCM Cookie - 优先用 curl 直接调用（因为 mify 运行环境可能无法访问某些接口）"""
        # 方案1：curl 直接调用
        try:
            cmd = ["curl", "-s", "--connect-timeout", "10", cookie_url]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            output = result.stdout
            if output:
                data = json.loads(output)
                cookie = data.get("data", {}).get("result", {}).get("cookie", "")
                if cookie:
                    print(f"  📌 cookie = {cookie[:50]}...")
                    return cookie
        except Exception as e:
            print(f"  ⚠️ curl 获取 Cookie 失败: {e}")

        # 方案2：回退到 mify HTTP workflow
        resp = self.http_call(cookie_url, "get")
        cookie = resp.get("body", {}).get("data", {}).get("result", {}).get("cookie", "")
        return cookie
