# AgenticArxiv/agents/agent_engine.py
import json
import re
import sys
import os
from typing import Dict, Any, Optional, Tuple, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.llm_client import LLMClient
from tools.tool_registry import registry
from agents.base_agent import BaseAgent
from agents.prompt_templates import get_react_prompt, format_tool_description
from utils.logger import log


class ReActAgent(BaseAgent):
    """方案 A: ReAct + 正则解析 Agent"""

    def __init__(self, llm_client: LLMClient):
        super().__init__(llm_client)
        try:
            import tools.arxiv_tool  # noqa: F401
            import tools.openalex_tool  # noqa: F401
            import tools.pdf_download_tool  # noqa: F401
            import tools.pdf_translate_tool  # noqa: F401
            import tools.cache_status_tool  # noqa: F401
            import tools.rag_tool  # noqa: F401
            log.info(f"已导入工具模块，注册了 {len(registry.list_tools())} 个工具")
        except ImportError as e:
            log.warning(f"导入工具模块失败: {e}")

    def discover_tools(self) -> List[Dict[str, Any]]:
        return registry.list_tools()

    def build_messages(
        self, task: str, tools_description: str, history_text: str
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        prompt = get_react_prompt(
            task=task,
            tools_description=tools_description,
            history=history_text,
        )
        return [{"role": "user", "content": prompt}], {}

    def parse_response(self, raw_response: Dict) -> Tuple[str, Optional[Dict[str, Any]]]:
        content = (
            raw_response.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        log.debug(f"LLM响应: {content}")
        return self._parse_react_text(content)

    def invoke_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        return registry.execute_tool(tool_name, args)

    # ---------- 正则解析逻辑 ----------

    def _parse_react_text(self, response: str) -> Tuple[str, Optional[Dict[str, Any]]]:
        log.debug(f"解析LLM响应: {response[:200]}...")
        # 模型在 FINISH 之后追加的自然语言答复（由 base_agent 用作最终回复）
        self.final_answer_text = ""

        thought_match = re.search(
            r"Thought:\s*(.*?)(?=\nAction:|$)", response, re.DOTALL
        )
        thought = thought_match.group(1).strip() if thought_match else "未提供思考过程"

        action_match = re.search(
            r"Action:\s*(.*?)(?=\nObservation:|$)", response, re.DOTALL
        )
        action_text = action_match.group(1).strip() if action_match else ""

        log.info(f"提取到的Action文本: {action_text}")

        if action_text.upper().startswith("FINISH"):
            log.info("Agent决定结束任务")
            # 模型可能把最终答复写在 "Action: FINISH" 之后，也可能写在它之前，
            # 两种形式都要保留，否则 /chat 只剩一句"任务完成"
            answer = action_text[len("FINISH"):].strip()
            if not answer and action_match:
                prefix = response[: action_match.start()].strip()
                # 去掉开头的 Thought 段（"Thought: ...\n\n<答案>"）
                if prefix.startswith("Thought:"):
                    parts = re.split(r"\n\s*\n", prefix, maxsplit=1)
                    prefix = parts[1].strip() if len(parts) == 2 else ""
                # 去掉结尾的 Thought 段（"<答案>\n\nThought: ..."）
                tail_idx = prefix.rfind("\nThought:")
                if tail_idx != -1:
                    prefix = prefix[:tail_idx].strip()
                if len(prefix) > 10:
                    answer = prefix
            self.final_answer_text = answer
            return thought, None

        # JSON 解析
        try:
            json_match = re.search(r"({.*})", action_text, re.DOTALL)
            if json_match:
                action_json = json.loads(json_match.group(1))
                if isinstance(action_json, dict):
                    if "name" in action_json and "args" in action_json:
                        action_dict = {
                            "name": action_json["name"],
                            "args": action_json["args"],
                        }
                    else:
                        tool_names = [tool["name"] for tool in registry.list_tools()]
                        if tool_names:
                            action_dict = {"name": tool_names[0], "args": action_json}
                        else:
                            raise ValueError("没有可用的工具")
                    log.info(f"解析成功: 工具={action_dict['name']}, 参数={action_dict['args']}")
                    return thought, action_dict
        except json.JSONDecodeError as e:
            log.error(f"JSON解析失败: {e}, Action文本: {action_text}")

        # 文本降级提取：只接受"动作片段"，避免把正文里提到的工具名误当成调用
        snippet = action_text.strip()
        tool_names = [tool["name"] for tool in registry.list_tools()]
        looks_like_call = any(
            re.match(rf"^\s*`?{re.escape(n)}`?\b", snippet) for n in tool_names
        )
        if len(snippet) > 300 and not looks_like_call:
            log.warning("Action 文本过长，按最终答复处理（不执行工具）")
            self.final_answer_text = snippet
            return thought, None
        log.warning("尝试从文本中提取工具调用信息")
        for tool_name in tool_names:
            if re.match(rf"^\s*`?{re.escape(tool_name)}`?\b", action_text):
                args = {}
                if "max_results" in action_text:
                    max_match = re.search(r"max_results[=\s:]+(\d+)", action_text)
                    if max_match:
                        args["max_results"] = int(max_match.group(1))
                if "aspect" in action_text:
                    aspect_match = re.search(r'aspect[=\s:]+["\']?([A-Z*]+)["\']?', action_text)
                    if aspect_match:
                        args["aspect"] = aspect_match.group(1)
                if "days" in action_text:
                    days_match = re.search(r"days[=\s:]+(\d+)", action_text)
                    if days_match:
                        args["days"] = int(days_match.group(1))
                log.info(f"从文本提取: 工具={tool_name}, 参数={args}")
                return thought, {"name": tool_name, "args": args}

        log.error(f"无法解析Action: {action_text}")
        return thought, None
