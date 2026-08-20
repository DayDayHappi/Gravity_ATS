"""测试报告生成器：JSON + JUnit XML + HTML + 控制台汇总。

- JSON:  ``reports/<ts>/result.json``  机器可读，含每条用例详情
- JUnit: ``reports/<ts>/junit.xml``    CI 集成（Jenkins/GitLab）
- HTML:  ``reports/<ts>/report.html``  人可读（jinja2 渲染，无 jinja2 则退化为纯文本表）
- 控制台: 退出前打印汇总（总数/通过/失败/跳过/通过率/总耗时）
"""
import os
import json
import datetime as _dt

from . import logger
from .result import PASSED, FAILED, SKIPPED, ERROR


def _summary(results: list) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.status == PASSED)
    failed = sum(1 for r in results if r.status == FAILED)
    skipped = sum(1 for r in results if r.status == SKIPPED)
    errored = sum(1 for r in results if r.status == ERROR)
    elapsed = sum(r.elapsed_ms for r in results)
    return {
        "total": total, "passed": passed, "failed": failed,
        "skipped": skipped, "errored": errored,
        "pass_rate": round(passed / total * 100, 1) if total else 0.0,
        "total_elapsed_ms": elapsed,
    }


def _result_to_dict(r):
    return {
        "name": r.name, "module": r.module, "status": r.status,
        "elapsed_ms": r.elapsed_ms, "message": r.message,
        "detail": r.detail, "timestamp": r.timestamp,
        "scenario": r.scenario, "cycle": r.cycle,
    }


def _scenario_stats(results: list) -> dict:
    """按场景聚合统计：每场景的 cycle 集合 + 每模块 pass/fail/skip/error 计数。"""
    stats = {}
    for r in results:
        key = r.scenario or "?"
        sc = stats.setdefault(key, {"cycles": set(), "modules": {}})
        sc["cycles"].add(r.cycle)
        mod = sc["modules"].setdefault(
            r.module, {"pass": 0, "fail": 0, "skip": 0, "error": 0})
        if r.status == PASSED:
            mod["pass"] += 1
        elif r.status == FAILED:
            mod["fail"] += 1
        elif r.status == SKIPPED:
            mod["skip"] += 1
        elif r.status == ERROR:
            mod["error"] += 1
    # 把 set 转成可 JSON 序列化的 count
    for sc in stats.values():
        sc["cycles"] = len(sc["cycles"])
    return stats


def write_json(results: list, out_dir: str) -> str:
    summary = _summary(results)
    data = {
        "summary": summary,
        "scenario_stats": _scenario_stats(results),
        "results": [_result_to_dict(r) for r in results],
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    path = os.path.join(out_dir, "result.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write_junit(results: list, out_dir: str) -> str:
    """生成 JUnit XML（testsuite 含多个 testcase）。"""
    summary = _summary(results)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(
        f'<testsuite name="VX100_EVB" tests="{summary["total"]}" '
        f'failures="{summary["failed"]}" errors="{summary["errored"]}" '
        f'skipped="{summary["skipped"]}" '
        f'time="{summary["total_elapsed_ms"]/1000:.2f}">'
    )
    for r in results:
        lines.append(
            f'  <testcase name="{_xml_escape(r.name)}" classname="{r.module}" '
            f'time="{r.elapsed_ms/1000:.2f}">'
        )
        if r.status == FAILED:
            lines.append(f'    <failure message="{_xml_escape(r.message)}"><![CDATA[{r.detail}]]></failure>')
        elif r.status == ERROR:
            lines.append(f'    <error message="{_xml_escape(r.message)}"><![CDATA[{r.detail}]]></error>')
        elif r.status == SKIPPED:
            lines.append(f'    <skipped message="{_xml_escape(r.message)}" />')
        lines.append('  </testcase>')
    lines.append('</testsuite>')
    path = os.path.join(out_dir, "junit.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def _xml_escape(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


_HTML_TPL = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>VX100 EVB 测试报告</title>
<style>
body{font-family:sans-serif;margin:20px;background:#f5f5f5}
h1{color:#333}.summary{display:flex;gap:16px;margin:16px 0;flex-wrap:wrap}
.card{background:#fff;padding:16px 24px;border-radius:8px;box-shadow:0 1px 3px #aaa;text-align:center}
.card .num{font-size:28px;font-weight:bold}
.card .lbl{color:#666;font-size:13px}
.pass{color:#2e7d32}.fail{color:#c62828}.skip{color:#f9a825}
table{width:100%;border-collapse:collapse;background:#fff;box-shadow:0 1px 3px #aaa}
th,td{padding:8px 12px;border-bottom:1px solid #eee;text-align:left;font-size:13px}
th{background:#eee}.st-PASS{color:#2e7d32;font-weight:bold}
.st-FAIL{color:#c62828;font-weight:bold}.st-SKIP{color:#f9a825}
.st-ERROR{color:#6a1b9a;font-weight:bold}
</style></head><body>
<h1>VX100 EVB 自动化测试报告</h1>
<div class="summary">
  <div class="card"><div class="num">{{total}}</div><div class="lbl">总用例</div></div>
  <div class="card"><div class="num pass">{{passed}}</div><div class="lbl">通过</div></div>
  <div class="card"><div class="num fail">{{failed}}</div><div class="lbl">失败</div></div>
  <div class="card"><div class="num skip">{{skipped}}</div><div class="lbl">跳过</div></div>
  <div class="card"><div class="num">{{pass_rate}}%</div><div class="lbl">通过率</div></div>
  <div class="card"><div class="num">{{elapsed}}s</div><div class="lbl">总耗时</div></div>
</div>
<table><tr><th>用例</th><th>模块</th><th>状态</th><th>耗时</th><th>信息</th><th>详情</th></tr>
{% for r in results %}
<tr>
  <td>{{r.name}}</td><td>{{r.module}}</td>
  <td class="st-{{r.status}}">{{r.status}}</td>
  <td>{{r.elapsed_ms}}ms</td><td>{{r.message}}</td>
  <td><pre>{{r.detail}}</pre></td>
</tr>
{% endfor %}
</table>
</body></html>"""


def write_html(results: list, out_dir: str) -> str:
    summary = _summary(results)
    try:
        from jinja2 import Template
        tpl = Template(_HTML_TPL)
        html = tpl.render(
            total=summary["total"], passed=summary["passed"],
            failed=summary["failed"], skipped=summary["skipped"],
            pass_rate=summary["pass_rate"],
            elapsed=round(summary["total_elapsed_ms"] / 1000, 1),
            results=[_result_to_dict(r) for r in results],
        )
    except ImportError:
        # 无 jinja2：退化为基础 HTML 表格
        rows = "".join(
            f"<tr><td>{r.name}</td><td>{r.module}</td><td>{r.status}</td>"
            f"<td>{r.elapsed_ms}ms</td><td>{r.message}</td><td><pre>{r.detail}</pre></td></tr>"
            for r in results
        )
        html = (
            f"<html><body><h1>测试报告</h1>"
            f"<p>通过 {summary['passed']}/{summary['total']}（{summary['pass_rate']}%）</p>"
            f"<table border=1>{rows}</table></body></html>"
        )
    path = os.path.join(out_dir, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def print_summary(results: list):
    s = _summary(results)
    logger.step("=" * 50)
    logger.step(f"测试完成：共 {s['total']} 项 | "
                f"通过 {s['passed']} | 失败 {s['failed']} | "
                f"跳过 {s['skipped']} | 错误 {s['errored']} | "
                f"通过率 {s['pass_rate']}% | 总耗时 {s['total_elapsed_ms']/1000:.1f}s")
    # 场景维度统计
    stats = _scenario_stats(results)
    for sc_name, sc in stats.items():
        line = f"  场景 [{sc_name}] cycles={sc['cycles']}"
        for mod, m in sc["modules"].items():
            line += f" | {mod}: 过{m['pass']}/败{m['fail']}/跳{m['skip']}/错{m['error']}"
        logger.step(line)
    logger.step("=" * 50)


def generate(results: list, out_dir: str, junit: bool = True, html: bool = True) -> dict:
    """生成全部报告，返回各文件路径。"""
    os.makedirs(out_dir, exist_ok=True)
    paths = {"json": write_json(results, out_dir)}
    if junit:
        paths["junit"] = write_junit(results, out_dir)
    if html:
        paths["html"] = write_html(results, out_dir)
    print_summary(results)
    for k, p in paths.items():
        logger.info(f"  {k} 报告: {p}")
    return paths
