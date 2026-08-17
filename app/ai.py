"""AI 集成：OpenAI 兼容接口调用（DeepSeek / OpenAI / 本地 Ollama 通用）。

依赖标准库 urllib，零额外依赖。密钥、base_url、模型名均来自数据库 ai_models 表，
用户可在设置面板里添加多个 key 来接入不同模型。
"""
import json
import re
import urllib.error
import urllib.request
import zipfile
from typing import List, Optional

from .database import AiModel, Todo, PRIORITY_LABELS

# 常见服务预设（用户点一下即可快速添加，只需填 key）
PRESET_MODELS = [
    {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "hint": "https://platform.deepseek.com 获取 key",
    },
    {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "hint": "https://platform.openai.com 获取 key",
    },
    {
        "name": "本地 Ollama",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen3:8b",
        "hint": "本地无需真实 key，随便填如 ollama",
    },
]


class AiError(Exception):
    pass


def call_chat_completion(
    base_url: str,
    api_key: str,
    model: str,
    messages: List[dict],
    temperature: float = 0.7,
    timeout: int = 60,
) -> str:
    """调用 OpenAI 兼容的 /chat/completions，返回首个 assistant 回复文本。"""
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise AiError(f"HTTP {e.code}: {detail[:300]}")
    except urllib.error.URLError as e:
        raise AiError(f"网络错误：{e.reason}")
    except json.JSONDecodeError:
        raise AiError("返回内容不是合法 JSON")

    choices = data.get("choices") or []
    if not choices:
        raise AiError(f"模型未返回内容：{json.dumps(data, ensure_ascii=False)[:300]}")
    msg = choices[0].get("message") or {}
    content = msg.get("content") or ""
    if not content:
        raise AiError("模型返回了空内容")
    return content.strip()


def build_report_prompt(sections, scope_label: str) -> List[dict]:
    """把待办记录拼成提示词，让 AI 生成总结。

    sections: [(标签, [Todo...]), ...]，例如 [("今日新建", created), ("今日完成", done)]
    """
    parts = []
    total = 0
    for label, todos in sections:
        sec = [f"【{label}】"]
        if todos:
            for t in todos:
                pri = PRIORITY_LABELS.get(t.priority, t.priority)
                sec.append(
                    f"- [{pri}] {t.title}"
                    + (f"（{t.description}）" if t.description else "")
                )
        else:
            sec.append("（无）")
        parts.append("\n".join(sec))
        total += len(todos)

    body = "\n\n".join(parts)

    system = (
        "你是一名高效的工作助理，负责把用户的待办工作记录整理成简洁、专业的"
        f"{scope_label}总结。要求：1) 提炼重点与进展；2) 区分给出的各分类；"
        "3) 有风险或建议可简短补充；4) 用中文输出，分点但不要冗长。"
    )
    user = (
        f"以下是我{scope_label}的工作情况（共 {total} 项）：\n{body}\n\n"
        f"请生成{scope_label}总结。"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate_report_summary(model_cfg: AiModel, sections, scope_label: str) -> str:
    messages = build_report_prompt(sections, scope_label)
    return call_chat_completion(
        model_cfg.base_url, model_cfg.api_key, model_cfg.model, messages
    )


def parse_natural_language_todo(model_cfg: AiModel, text: str, categories, today_str: str) -> dict:
    """让 AI 把一句话待办描述解析成结构化字段，返回 dict。"""
    cat_names = [c.name for c in categories]
    system = (
        "你是待办解析助手。把用户的中文任务描述解析成结构化 JSON，"
        "只返回 JSON 对象本身，不要任何额外文字、解释或 markdown 代码块。"
    )
    user = (
        f"今天是 {today_str}。\n"
        f"用户输入：{text}\n"
        f"可选分类：{', '.join(cat_names) if cat_names else '（无，用空字符串）'}\n"
        "请解析并返回如下 JSON（字段值用中文；due_date 为 YYYY-MM-DD，"
        "没有截止日期则用空字符串；相对日期如「明天/后天/下周X」换算成具体日期）：\n"
        '{"title": "任务标题", "description": "补充说明(可空)", '
        '"priority": "high|medium|low", "due_date": "YYYY-MM-DD 或 \\"\\"", '
        '"category": "分类名(尽量匹配可选分类，否则空字符串)"}'
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw = call_chat_completion(
        model_cfg.base_url, model_cfg.api_key, model_cfg.model, messages, temperature=0.2
    )
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        raw = m.group(0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise AiError(f"AI 返回的不是合法 JSON：{raw[:200]}") from e

    title = str(data.get("title", "")).strip() or text.strip()[:50]
    priority = data.get("priority", "medium")
    if priority not in ("high", "medium", "low"):
        priority = "medium"
    due = str(data.get("due_date", "")).strip()
    if due and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
        due = ""
    desc = str(data.get("description", "")).strip()
    category = str(data.get("category", "")).strip()
    return {
        "title": title,
        "description": desc,
        "priority": priority,
        "due_date": due,
        "category": category,
    }


# ---------------------------------------------------------------- 附件总结
MAX_EXTRACT_CHARS = 8000  # 送给 AI 的文本上限（避免超长与高额 token）


def extract_text_from_file(file_path: str, file_name: str) -> str:
    """从 docx / txt / md 附件中提取纯文本（纯标准库实现）。

    - .docx：zipfile 读 word/document.xml，解析 <w:t> 文本
    - .txt / .md：直接按 utf-8 读（失败回退 gbk）
    - 其他格式：返回空字符串（不支持自动总结）
    """
    name = (file_name or "").lower()
    try:
        if name.endswith(".docx"):
            with zipfile.ZipFile(file_path) as zf:
                xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
            # 按段落拆，保留换行；<w:t> 里的文本拼起来
            paras = re.findall(r"<w:p[ >].*?</w:p>", xml, re.DOTALL)
            lines = []
            for p in paras:
                texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.DOTALL)
                line = "".join(texts)
                line = line.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                if line.strip():
                    lines.append(line.strip())
            return "\n".join(lines)[:MAX_EXTRACT_CHARS]
        if name.endswith((".txt", ".md", ".markdown")):
            for enc in ("utf-8", "gbk", "utf-16"):
                try:
                    with open(file_path, "r", encoding=enc) as f:
                        return f.read()[:MAX_EXTRACT_CHARS]
                except (UnicodeDecodeError, UnicodeError):
                    continue
        return ""
    except Exception:
        return ""


def summarize_attachment(model_cfg: AiModel, file_path: str, file_name: str) -> str:
    """用 AI 把附件总结成 1-2 句「文件精髓」。

    仅支持 docx / txt / md；其他格式或提取不到文本时抛 AiError。
    """
    text = extract_text_from_file(file_path, file_name)
    if not text.strip():
        raise AiError("该附件不是 docx/txt 格式或无法读取内容，无法自动总结")
    system = (
        "你是文档速读助手。请用 1-2 句中文概括文件的精髓：核心内容、关键结论或用途，"
        "让用户不看原文也能知道这个文件是干什么的。不要罗列细节，不要超过 2 句。"
    )
    user = f"文件名：{file_name}\n\n文件内容（节选）：\n{text[:MAX_EXTRACT_CHARS]}\n\n请给出 1-2 句精髓总结。"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return call_chat_completion(
        model_cfg.base_url, model_cfg.api_key, model_cfg.model, messages, temperature=0.3
    )
