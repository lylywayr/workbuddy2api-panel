#!/usr/bin/env python3
"""check_task_coverage.py —— 检查上游新任务是否已被 autoActions 覆盖。

背景：面板用 autoActionFor(task_code) != nil 判断任务能否自动执行。
上游新上的活动任务如果 task_code 不在 internal/panel/autotask.go 的
autoActions 表里，面板会**显示**它，但永远不会自动去做。

用法：
    python scripts/check_task_coverage.py

输出：
    - 已覆盖任务数 / 上游任务总数
    - 未覆盖任务清单（含标题、奖励、进度），按奖励从高到低排序
    - 每条未覆盖任务的建议处理方式

依赖：仅标准库；需要 wb2api 正在运行且 config.json 里有 api_key。
"""

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _fix_console():
    """Windows 控制台默认 GBK，中文会炸。尽量切 UTF-8。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def load_config():
    cfg_path = ROOT / "config.json"
    if not cfg_path.exists():
        sys.exit(f"找不到配置文件：{cfg_path}")
    with open(cfg_path, encoding="utf-8") as f:
        return json.load(f)


def api_get(base, key, path):
    req = urllib.request.Request(base + path, headers={
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200]
        raise SystemExit(f"接口 {path} 返回 HTTP {e.code}：{body}")
    except urllib.error.URLError as e:
        raise SystemExit(f"连不上服务（{base}）：{e.reason}\n服务没启动？先运行 wb2api.exe")


def supported_codes():
    """从 autotask.go 解析已实现的 TaskCode。"""
    src = (ROOT / "internal" / "panel" / "autotask.go").read_text(encoding="utf-8")
    return set(re.findall(r'TaskCode:\s*"([^"]+)"', src))


def fetch_tasks(base, key, uid):
    """拉单个账号的任务列表，兼容两种响应外形。"""
    data = api_get(base, key, f"/panel/api/accounts/{uid}/tasks")
    if isinstance(data, list):
        return data
    for k in ("tasks", "items", "data"):
        if isinstance(data.get(k), list):
            return data[k]
    return []


def suggest(task):
    """给出补这个任务的难度判断。"""
    code = (task.get("task_code") or "").lower()
    cur, tgt = task.get("current") or 0, task.get("target") or 0
    if task.get("claimed") or task.get("accept_status") == "claimed":
        return "已领取 —— 无需处理"
    if tgt and cur >= tgt:
        return "已达标未领 —— 跑一次补领清扫即可，不用写代码"
    text = f"{task.get('title') or ''} {task.get('task_desc') or ''}"
    if "专家" in text or "召唤" in text or any(w in code for w in ("expert_use", "expert")):
        return "专家体验类 —— 可复用 DesktopExpertSummonSequence + DesktopChatWithExpert 链路"
    if any(w in code for w in ("checkin", "sign", "daily", "login")):
        return "签到类 —— 大概率复用现有 report 事件，改动小"
    if any(w in code for w in ("chat", "model", "conversation")):
        return "对话类 —— 可复用 ReportChatActivity 打点，通常不用真聊"
    if any(w in code for w in ("travel", "buddy", "cat")):
        return "Buddy 系 —— 已有 travel/first 链路，可复用"
    return "未知判据 —— 需逆向客户端行为事件（最难的一档）"


def main():
    _fix_console()
    cfg = load_config()
    key = cfg.get("api_key", "")
    if not key:
        sys.exit("config.json 里 api_key 为空，无法调用面板接口")

    listen = cfg.get("listen", "127.0.0.1:7863")
    host = listen if ":" in listen else f"{listen}:7863"
    if host.startswith(":"):
        host = "127.0.0.1" + host
    base = f"http://{host}"

    supported = supported_codes()
    ov = api_get(base, key, "/panel/api/overview")
    accounts = ov.get("accounts") or []

    print(f"面板      {base}  (v{ov.get('version', '?')})")
    print(f"账号数    {len(accounts)}")
    print(f"已实现    {len(supported)} 个任务动作")
    print()

    if not accounts:
        print("账号池是空的，拉不到上游任务列表。")
        print("请先在面板「添加账号」完成 OAuth 登录，再跑本脚本。")
        return

    all_rows = {}
    for acc in accounts:
        uid = acc.get("uid") or acc.get("id") or ""
        if not uid:
            continue
        name = acc.get("remark") or acc.get("nickname") or uid[:8]
        try:
            tasks = fetch_tasks(base, key, uid)
        except SystemExit as e:
            print(f"[{name}] 拉取失败：{e}")
            continue
        print(f"[{name}] 上游下发 {len(tasks)} 个任务")
        for t in tasks:
            code = t.get("task_code") or ""
            if code and code not in all_rows:
                all_rows[code] = t

    if not all_rows:
        print("\n没有拿到任何任务。可能是登录态失效（重新登录试试），或接口形状变了。")
        return

    missing = {c: t for c, t in all_rows.items() if c not in supported}
    covered = [c for c in all_rows if c in supported]

    print()
    print("=" * 68)
    print(f"覆盖情况：{len(covered)}/{len(all_rows)} 已实现")
    print("=" * 68)

    if not missing:
        print("\n全部已覆盖，无需改动。")
        return

    rows = sorted(
        missing.items(),
        key=lambda kv: (-(kv[1].get("credit") or 0), kv[0]),
    )
    print(f"\n未覆盖 {len(rows)} 个，按奖励从高到低：\n")
    for code, t in rows:
        title = t.get("title") or t.get("task_desc") or ""
        credit = t.get("credit") or 0
        energy = t.get("energy") or 0
        cur, tgt = t.get("current") or 0, t.get("target") or 0
        prog = f"{cur}/{tgt}" if tgt else "—"
        print(f"  {code}")
        print(f"    标题   {title}")
        print(f"    奖励   {credit} 积分 / {energy} 能量")
        print(f"    进度   {prog}")
        print(f"    建议   {suggest(t)}")
        print()

    out = ROOT / "data" / "task-coverage.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "all": all_rows, "covered": covered, "missing": list(missing.keys()),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完整明细已写入 {out}")


if __name__ == "__main__":
    main()
