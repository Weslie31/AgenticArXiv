# AgenticArxiv/agents/base_agent.py
import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple, List

from utils.llm_client import LLMClient
from utils.logger import log
from config import settings
from models.schemas import Paper
from models.store import store
from services.log_service import log_service
from services.runtime import translate_runner, event_bus
from tools.tool_registry import registry
from utils.pdf_resolver import resolve_pdf_url


def _openalex_dict_to_paper(p: Dict[str, Any]) -> Paper:
    """将 OpenAlex 返回的论文 dict 映射为 Paper schema

    pdf_url 使用智能解析器（resolve_pdf_url）尝试找到可下载的 PDF，
    按优先级尝试：OpenAlex OA URL → arXiv 镜像 → Unpaywall → Semantic Scholar。
    """
    authors = p.get("authors", [])
    if isinstance(authors, list):
        if authors and isinstance(authors[0], dict):
            authors = [a.get("name", a.get("display_name", "")) for a in authors]
    else:
        authors = []

    # 收集所有链接供 links 字段备用（原始 URL，不过滤）
    links: List[str] = []
    for loc_key in ("best_oa_location", "primary_location"):
        loc = p.get(loc_key)
        if isinstance(loc, dict):
            pdf = loc.get("pdf_url")
            if pdf and pdf not in links:
                links.append(pdf)
    if p.get("pdf_url") and p["pdf_url"] not in links:
        links.append(p["pdf_url"])

    # OpenAlex 的 publication_date 格式如 "2021-03-15"
    published = p.get("publication_date") or p.get("year") or None
    if isinstance(published, int):
        published = str(published)

    topics = p.get("topics") or []
    primary_topic = topics[0].get("display_name") if topics else None

    doi = p.get("doi") or ""
    if doi.startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/"):]

    # 智能 PDF URL 解析：优先用 arXiv 镜像，其他返回候选 URL 由下载时验证
    best_oa = p.get("best_oa_location") or {}
    primary_loc = p.get("primary_location") or {}
    openalex_best_url = best_oa.get("pdf_url")
    all_links: List[str] = list(links)  # 已有 links
    if openalex_best_url and openalex_best_url not in all_links:
        all_links.append(openalex_best_url)

    pdf_url = resolve_pdf_url(
        doi=doi,
        openalex_pdf_url=primary_loc.get("pdf_url"),
        openalex_best_url=best_oa.get("pdf_url"),
        openalex_id=p.get("openalex_id") or p.get("id", ""),
        links=all_links,
    )

    # 论文详情页 URL（不是 PDF 下载 URL）
    # 优先级：DOI 链接 > OpenAlex 详情页
    paper_url: Optional[str] = None
    if doi:
        paper_url = f"https://doi.org/{doi}"
    else:
        oid = p.get("openalex_id")
        if oid:
            if oid.startswith("https://openalex.org/"):
                paper_url = oid
            else:
                paper_url = f"https://openalex.org/{oid}"

    return Paper(
        id=doi or p.get("openalex_id") or p.get("id", ""),
        title=p.get("title", "无标题"),
        authors=authors,
        summary=p.get("abstract", p.get("abstract_text", "")),
        published=published,
        updated=None,
        pdf_url=pdf_url,
        paper_url=paper_url,
        primary_category=primary_topic,
        categories=[t.get("display_name", "") for t in topics],
        links=links,
    )


class BaseAgent(ABC):
    """所有 Agent 方案的基类，封装通用的循环控制、日志、SSE、副作用逻辑"""

    agent_type: str = "regex"  # 子类覆写

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.max_iterations = 5
        self.session_id = "default"
        # 本轮是否已把检索结果写入会话（同一轮只保留第一次检索的结果，
        # 避免模型为"核验"再搜一次时把额外结果也塞进论文区）
        self._search_stored_in_run = False
        # 自我评估器（延迟加载避免循环导入）
        self._self_evaluator = None
        self._retry_decider = None

    # ---------- 子类必须实现 ----------

    @abstractmethod
    def discover_tools(self) -> List[Dict[str, Any]]:
        """返回可用工具列表 [{name, description, parameters}]"""

    @abstractmethod
    def build_messages(
        self, task: str, tools_info: List[Dict], history_text: str
    ) -> Tuple[List[Dict], Dict[str, Any]]:
        """构造 LLM 请求。返回 (messages, extra_payload)"""

    @abstractmethod
    def parse_response(self, raw_response: Dict) -> Tuple[str, Optional[Dict[str, Any]]]:
        """解析 LLM 响应。返回 (thought, action_dict | None 表示 FINISH)"""

    @abstractmethod
    def invoke_tool(self, tool_name: str, args: Dict[str, Any]) -> Any:
        """执行工具，返回原始结果"""

    # ---------- 子类可选覆写 ----------

    def format_tools_for_prompt(self, tools: List[Dict]) -> str:
        """将工具列表格式化为 prompt 中的文本描述，子类可覆写"""
        from agents.prompt_templates import format_tool_description
        return format_tool_description(tools)

    def format_history(self, steps: list) -> str:
        """将历史步骤格式化为 prompt 中的文本，子类可覆写。
        如果步骤带评估信息，会附带 EvalQuality / EvalHint，方便 LLM 自我纠错。"""
        parts = []
        for s in steps:
            eval_line = ""
            if s.get("eval_quality"):
                eval_line = f"\nEvalQuality: {s['eval_quality']}"
                if s.get("eval_reason"):
                    eval_line += f" ({s['eval_reason']})"
                if s.get("need_retry"):
                    eval_line += f"\nEvalHint: {s.get('improvement_hint', '')}"
            parts.append(
                f"Thought: {s['thought']}\nAction: {s['action']}\nObservation: {s['observation']}{eval_line}"
            )
        return "\n\n".join(parts)

    # ---------- 通用执行循环 ----------

    def run(
        self,
        task: str,
        agent_model: str = None,
        session_id: str = "default",
    ) -> Dict[str, Any]:
        log.info(f"[{self.__class__.__name__}] 开始执行任务: {task}")
        run_start = time.time()
        self.session_id = session_id
        msg_id = uuid.uuid4().hex

        # Model resolution priority:
        #   1. Explicit agent_model argument (request-level override)
        #   2. LLM_MODEL env var
        #   3. settings.models.agent_model (system default)
        if agent_model is None:
            agent_model = os.getenv("LLM_MODEL") or settings.models.agent_model
        self.agent_model = agent_model

        try:
            log_service.create_chat_log(
                session_id=session_id,
                msg_id=msg_id,
                role="user",
                content=task,
                model=agent_model,
                agent_type=self.agent_type,
            )
        except Exception as e:
            log.warning(f"Failed to log user message: {e}")

        tools = self.discover_tools()
        tools_description = self.format_tools_for_prompt(tools)

        # 注入会话上下文，避免 LLM 重复搜索已缓存的论文
        enriched_task = self._enrich_task_with_context(task, session_id)

        history: List[Dict[str, str]] = []
        step_timings: List[Dict[str, int]] = []
        step_evaluations: List[Any] = []
        # 每个工具的重试计数（key=tool_name，value=已重试次数）
        tool_retry_counts: Dict[str, int] = {}
        if hasattr(self, "final_answer_text"):
            self.final_answer_text = ""
        self._search_stored_in_run = False
        token_usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        # 自我评估（延迟导入避免循环）
        self_evaluator = self._get_self_evaluator()
        retry_decider = self._get_retry_decider()

        for iteration in range(self.max_iterations):
            log.info(f"第 {iteration + 1} 次迭代")

            history_text = self.format_history(history)
            messages, extra = self.build_messages(enriched_task, tools_description, history_text)

            llm_ms = 0
            tool_ms = 0
            thought = ""
            action_dict = None
            observation = ""

            try:
                t0 = time.time()
                response = self.llm_client.chat_completions(
                    model=agent_model,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=2000,
                    stream=False,
                    extra=extra or None,
                )
                llm_ms = int((time.time() - t0) * 1000)

                # 累计 token 用量
                usage = response.get("usage") or {}
                token_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                token_usage["completion_tokens"] += usage.get("completion_tokens", 0)
                token_usage["total_tokens"] += usage.get("total_tokens", 0)

                content = (
                    response.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                # 空响应重试一次
                if not content or not content.strip():
                    log.warning("LLM 返回空内容，重试...")
                    response = self.llm_client.chat_completions(
                        model=agent_model,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=2000,
                        stream=False,
                        extra=extra or None,
                    )
                    llm_ms += int((time.time() - t0) * 1000)
                    usage = response.get("usage") or {}
                    token_usage["prompt_tokens"] += usage.get("prompt_tokens", 0)
                    token_usage["completion_tokens"] += usage.get("completion_tokens", 0)
                    token_usage["total_tokens"] += usage.get("total_tokens", 0)

                thought, action_dict = self.parse_response(response)
                log.info(f"Thought: {thought}")

                if action_dict is None:
                    log.info("任务完成")
                    # 模型可能在 FINISH 后直接给出最终答复，优先保留它
                    observation = (getattr(self, "final_answer_text", "") or "").strip() or "任务完成"
                    history.append({"thought": thought, "action": "FINISH", "observation": observation})
                    step_timings.append({"llm_ms": llm_ms, "tool_ms": 0})
                    self._log_step(msg_id, iteration, thought, "FINISH", "{}", observation, llm_ms, 0, session_id)
                    break

                # 带副作用的工具执行
                t1 = time.time()
                observation = self._execute_with_side_effects(action_dict)
                tool_ms = int((time.time() - t1) * 1000)
                log.info(f"Observation: {observation[:200]}...")

                # ---------- 自我评估 + 自动重试决策 ----------
                tool_name = action_dict.get("name", "")
                tool_args = action_dict.get("args", {}) or {}
                tool_retry_count = tool_retry_counts.get(tool_name, 0)
                step_record = {
                    "thought": thought,
                    "action": json.dumps(action_dict, ensure_ascii=False),
                    "observation": observation,
                }
                step_eval = None
                try:
                    step_eval = self_evaluator.evaluate_step(
                        step_index=iteration,
                        tool_name=tool_name,
                        args=tool_args,
                        observation=observation,
                        retry_count=tool_retry_count,
                    )
                    step_evaluations.append(step_eval)
                    self._publish_evaluation(session_id, step_eval)
                    # 把评估摘要回填到 history，让下一步 LLM 看到上一次的质量
                    step_record.update(self._extract_eval_summary(step_eval))
                except Exception as e:
                    log.warning(f"[SelfEval] 评估失败不影响主流程: {e}")

                # 调用 RetryDecider 决定是否在同一迭代内立即重试该工具
                retry_handled = False
                if step_eval is not None:
                    try:
                        decision = retry_decider.decide(
                            tool_name=tool_name,
                            evaluation=step_eval,
                            retry_count=tool_retry_count,
                            observation=observation,
                        )
                        if decision.should_retry:
                            retry_handled = True
                            tool_retry_counts[tool_name] = tool_retry_count + 1
                            log.info(
                                f"[SelfEval] 触发自动重试: tool={tool_name}, "
                                f"reason={decision.reason}, "
                                f"budget_left={decision.retry_budget_left}"
                            )
                            # 记录重试事件到 SSE，前端可见
                            event_bus.publish(session_id, {
                                "type": "self_evaluation_retry",
                                "tool": tool_name,
                                "step_index": iteration,
                                "reason": decision.reason,
                                "quality_score": float(
                                    getattr(step_eval, "quality_score", 0.0)
                                    if not isinstance(step_eval, dict)
                                    else step_eval.get("quality_score", 0.0)
                                ),
                            })
                            # 增加迭代预算（最多 +2 次额外重试，避免无限循环）
                            self.max_iterations = max(self.max_iterations, iteration + 3)
                    except Exception as e:
                        log.warning(f"[SelfEval] RetryDecider 决策失败: {e}")

                step_timings.append({"llm_ms": llm_ms, "tool_ms": tool_ms})
                history.append(step_record)

                self._log_step(
                    msg_id, iteration, thought,
                    action_dict.get("name", ""), json.dumps(action_dict.get("args", {}), ensure_ascii=False),
                    observation[:4000], llm_ms, tool_ms, session_id,
                )

                # 重试时不增加外部迭代计数（让 LLM 在下一步基于原有问题继续决策）
                # 这里是"评估驱动的立即重试"，不需要再调 LLM，所以 continue 外层循环下次
                # 实际上 RetryDecider 触发的重试会以"下一轮 LLM 重新生成 action"的形式自然发生
                _ = retry_handled  # 占位以避免 lint 警告

                if iteration == self.max_iterations - 1:
                    log.warning("达到最大迭代次数，强制结束")
                    history.append({"thought": "达到最大迭代次数", "action": "FORCE_STOP", "observation": "迭代限制"})
                    self._log_step(msg_id, iteration + 1, "达到最大迭代次数", "FORCE_STOP", "", "迭代限制", 0, 0, session_id)
                    break

            except Exception as e:
                error_msg = f"LLM调用失败: {str(e)}"
                log.error(error_msg)
                history.append({"thought": "LLM调用失败", "action": "ERROR", "observation": error_msg})
                step_timings.append({"llm_ms": llm_ms, "tool_ms": 0})
                self._log_step(msg_id, iteration, "LLM调用失败", "ERROR", "", error_msg, llm_ms, 0, session_id)
                break

        final_observation = history[-1]["observation"] if history else "无执行结果"

        reply = ""
        for step in reversed(history):
            if step.get("action") not in ("FINISH", "FORCE_STOP", "ERROR"):
                reply = step.get("observation", "")
                break
        reply = reply or final_observation

        try:
            log_service.create_chat_log(
                                session_id=session_id,
                        msg_id=msg_id + "_reply",
                        role="assistant",
                        content=reply,
                        model=agent_model,
                        agent_type=self.agent_type,
                    )
        except Exception as e:
            log.warning(f"Failed to log assistant reply: {e}")

        total_time_ms = int((time.time() - run_start) * 1000)
        total_llm_ms = sum(s["llm_ms"] for s in step_timings)
        total_tool_ms = sum(s["tool_ms"] for s in step_timings)

        # ---------- 运行级整体自评 ----------
        overall_eval = self._evaluate_run_overall(
            task=task,
            history=history,
            step_evaluations=step_evaluations,
            total_iterations=len(history),
        )
        if overall_eval is not None:
            try:
                self._publish_evaluation(session_id, overall_eval)
            except Exception:
                pass

        result = {
            "task": task,
            "msg_id": msg_id,
            "history": history,
            "final_observation": final_observation,
            "total_time_ms": total_time_ms,
            "iteration_count": len(history),
            "agent_type": self.agent_type,
            "timing": {
                "total_llm_ms": total_llm_ms,
                "total_tool_ms": total_tool_ms,
                "framework_overhead_ms": total_time_ms - total_llm_ms - total_tool_ms,
                "steps": step_timings,
            },
            "token_usage": token_usage,
            "self_evaluation": self._build_self_evaluation_report(step_evaluations),
            "overall_evaluation": overall_eval.to_dict() if overall_eval is not None else None,
        }
        log.info(f"任务执行完成，共 {len(history)} 步, 总耗时 {total_time_ms}ms (LLM {total_llm_ms}ms + Tool {total_tool_ms}ms)")
        log.info("-" * 80)
        return result

    # ---------- 会话上下文 ----------

    def _enrich_task_with_context(self, task: str, session_id: str) -> str:
        """向任务描述注入当前会话状态"""
        try:
            papers = store.get_last_papers(session_id)
            if papers:
                titles = [f"  {i+1}. {p.title}" for i, p in enumerate(papers[:10])]
                ctx = f"\n\n[会话上下文] 当前会话已有 {len(papers)} 篇论文:\n" + "\n".join(titles)
                ctx += "\n如需获取新论文，请调用 get_recently_submitted_cs_papers。"
                return task + ctx
        except Exception:
            pass
        return task

    # ---------- 通用副作用逻辑 ----------

    def _execute_with_side_effects(self, action_dict: Dict[str, Any]) -> str:
        """统一处理 session_id 覆盖、翻译异步、paper 状态写入等副作用"""
        try:
            tool_name = action_dict["name"]
            args = action_dict.get("args", {}) or {}

            log.info(f"执行工具: {tool_name}, 参数: {args}")

            # 强制覆盖 session_id
            try:
                tool = registry.get_tool(tool_name)
                props = (tool or {}).get("parameters", {}).get("properties", {})
                if isinstance(args, dict) and ("session_id" in props):
                    args["session_id"] = self.session_id
            except Exception:
                pass

            # 验证工具存在
            available_tools = [t["name"] for t in registry.list_tools()]
            if tool_name not in available_tools:
                return f"错误: 工具 '{tool_name}' 不存在。可用工具包括: {', '.join(available_tools)}"

            # 搜索工具自动排除会话内已显示的论文（避免重复）
            # 适用于所有支持 exclude_paper_ids 参数的搜索工具：
            #   - get_recently_submitted_cs_papers (arxiv 工具)
            #   - search_openalex_papers (openalex 高级)
            #   - search_papers_nl (openalex NL 入口)
            _TOOLS_WITH_EXCLUDE_IDS = {
                "get_recently_submitted_cs_papers",
                "search_openalex_papers",
                "search_papers_nl",
            }
            if (
                tool_name in _TOOLS_WITH_EXCLUDE_IDS
                and isinstance(args, dict)
                and "exclude_paper_ids" not in args
            ):
                try:
                    existing_papers = store.get_last_papers(self.session_id)
                    if existing_papers:
                        existing_ids = [p.id for p in existing_papers if p.id]
                        if existing_ids:
                            args["exclude_paper_ids"] = existing_ids
                            log.info(
                                f"[{tool_name}] 自动注入 {len(existing_ids)} "
                                f"个已显示论文 ID 用于去重"
                            )
                except Exception as e:
                    log.debug(f"[{tool_name}] 注入已显示论文 ID 失败（忽略）: {e}")

            # 翻译工具异步 enqueue
            if tool_name == "translate_arxiv_pdf":
                t = translate_runner.enqueue(
                        session_id=self.session_id,
                    ref=args.get("ref", None),
                    force=bool(args.get("force", False)),
                    service=args.get("service") or settings.pdf2zh_service,
                    threads=int(args.get("threads") or settings.pdf2zh_threads),
                    keep_dual=bool(args.get("keep_dual", False)),
                    paper_id=args.get("paper_id"),
                    pdf_url=args.get("pdf_url"),
                    input_pdf_path=args.get("input_pdf_path"),
                )
                return (
                    f"已创建翻译任务 task_id={t.task_id}, paper_id={t.paper_id}，状态={t.status}。"
                    f"前端可订阅 SSE: /events?session_id={self.session_id}，"
                    f"任务完成后刷新 /translate/assets 或 /pdf/assets。"
                )

            # 调用子类实现的工具执行
            result = self.invoke_tool(tool_name, args)

            # paper_id 写入 last_active
            try:
                if isinstance(result, dict):
                    pid = result.get("paper_id")
                    if isinstance(pid, str) and pid.strip():
                        store.set_last_active_paper_id(self.session_id, pid.strip())
            except Exception:
                pass

            # search_papers_nl / search_openalex_papers 结果存入 session
            if tool_name in ("search_papers_nl", "search_openalex_papers"):
                if isinstance(result, dict) and "error" in result:
                    return f"工具执行失败: {result['error']}"
                if isinstance(result, list) and result:
                    papers_obj = [_openalex_dict_to_paper(p) for p in result]
                    if not self._search_stored_in_run:
                        store.set_last_papers(self.session_id, papers_obj)
                        self._search_stored_in_run = True
                    else:
                        log.info(
                            f"[{tool_name}] 本轮检索结果已写入，后续检索只用于推理，不再入库"
                        )
                    count = len(papers_obj)

                    # 展示标题 + 相关性分数，让 LLM 能判断结果质量
                    # result 是原始 dict 列表；只有 search_papers_nl 会带 _relevance_score，
                    # search_openalex_papers（布尔检索）没有分数字段，这里必须容忍 None。
                    scored = [
                        (p.title, r.get("_relevance_score"))
                        for p, r in zip(papers_obj, result)
                    ]
                    # 工具已经按 sort_by 排好序（相关度或时间），这里保持原顺序，
                    # 不再按分数二次排序，否则 sort_by="date" 会被打乱。
                    top = scored[:5]
                    order_label = (
                        "按时间排序"
                        if str(args.get("sort_by", "")).lower()
                        in ("date", "time", "year", "newest")
                        else "按相关性排序"
                    )
                    lines = [
                        f"  [{score:.1f}分] {title}" if isinstance(score, (int, float))
                        else f"  {title}"
                        for title, score in top
                    ]
                    titles_str = "\n".join(lines)

                    if count > 5:
                        return (
                            f"成功获取 {count} 篇论文（{order_label}）:\n{titles_str}\n"
                            f"  ... 还有 {count - 5} 篇"
                        )
                    else:
                        return f"成功获取 {count} 篇论文（{order_label}）:\n{titles_str}"
                elif isinstance(result, list) and not result:
                    return "未获取到任何论文，请尝试调整查询条件"
                else:
                    return f"成功获取记录数: {len(result) if isinstance(result, list) else '非列表'}"

            # arxiv 搜索结果存入 session
            elif tool_name == "get_recently_submitted_cs_papers":
                # MCP 模式可能返回 dict（如 {"error": "..."}），兼容处理
                if isinstance(result, dict):
                    if "error" in result:
                        return f"工具执行失败: {result['error']}"
                    vals = list(result.values())
                    if len(vals) == 1 and isinstance(vals[0], list):
                        result = vals[0]
                if isinstance(result, list):
                    if result:
                        papers_obj = [Paper(**p) for p in result]
                        if not self._search_stored_in_run:
                            store.set_last_papers(self.session_id, papers_obj)
                            self._search_stored_in_run = True
                        else:
                            log.info(
                                "[get_recently_submitted_cs_papers] 本轮检索结果已写入，"
                                "后续检索只用于推理，不再入库"
                            )
                        papers_count = len(result)
                        paper_titles = [paper.get("title", "无标题") for paper in result[:3]]
                        titles_str = "\n".join([f"  - {title}" for title in paper_titles])
                        if papers_count > 3:
                            return f"成功获取 {papers_count} 篇论文。示例论文:\n{titles_str}\n  ... 还有 {papers_count - 3} 篇论文"
                        else:
                            return f"成功获取 {papers_count} 篇论文:\n{titles_str}"
                    else:
                        return "未获取到任何论文记录，请尝试调整搜索参数（如增加天数范围）"
                else:
                    return f"工具返回结果格式异常: {type(result)}, 内容: {str(result)[:200]}"

            elif tool_name == "format_papers_console":
                return "FINISH"

            # 通用结果格式化
            if isinstance(result, list):
                return f"成功获取 {len(result)} 条记录"
            elif isinstance(result, str):
                return result[:1000] if len(result) > 1000 else result
            else:
                return str(result)[:1000]

        except Exception as e:
            error_msg = f"工具执行失败: {str(e)}"
            log.error(error_msg, exc_info=True)
            return error_msg

    # ---------- 日志 + SSE ----------

    def _log_step(
        self, msg_id: str, step_index: int,
        thought: str, action_name: str, action_args: str,
        observation: str, llm_ms: int, tool_ms: int,
        session_id: str,
    ):
        try:
            log_service.save_agent_step(
                msg_id=msg_id, step_index=step_index,
                thought=thought, action_name=action_name,
                action_args=action_args, observation=observation,
                llm_latency_ms=llm_ms, tool_latency_ms=tool_ms,
            )
            event_bus.publish(session_id, {
                "type": "agent_step",
                "step": {
                    "thought": thought, "action_name": action_name,
                    "observation": observation[:500], "step_index": step_index,
                    "llm_latency_ms": llm_ms, "tool_latency_ms": tool_ms,
                },
            })
        except Exception as e:
            log.warning(f"Failed to log step: {e}")

    # ---------- 自我评估辅助方法 ----------

    def _get_self_evaluator(self):
        """延迟加载 SelfEvaluator，避免循环导入"""
        if self._self_evaluator is None:
            try:
                from services.self_evaluator import SelfEvaluator
                self._self_evaluator = SelfEvaluator(
                    llm_client=self.llm_client,
                    model=getattr(self, "agent_model", None),
                )
            except Exception as e:
                log.warning(f"[SelfEval] 初始化失败，将退化为简单评估: {e}")
                from services.self_evaluator import SimpleSelfEvaluator
                self._self_evaluator = SimpleSelfEvaluator()
        return self._self_evaluator

    def _get_retry_decider(self):
        """延迟加载 RetryDecider"""
        if self._retry_decider is None:
            try:
                from services.retry_decider import RetryDecider
                self._retry_decider = RetryDecider()
            except Exception:
                from services.retry_decider import SimpleRetryDecider
                self._retry_decider = SimpleRetryDecider()
        return self._retry_decider

    def _publish_evaluation(self, session_id: str, evaluation: Any) -> None:
        """将单步评估结果推送到前端 SSE"""
        try:
            payload = evaluation
            if hasattr(evaluation, "to_dict"):
                payload = evaluation.to_dict()
            elif not isinstance(evaluation, dict):
                payload = {
                    "quality_score": float(getattr(evaluation, "quality_score", 0.5)),
                    "should_retry": bool(getattr(evaluation, "should_retry", False)),
                    "issues": list(getattr(evaluation, "issues", []) or []),
                    "suggestion": str(getattr(evaluation, "suggestion", "") or ""),
                }
            event_bus.publish(session_id, {
                "type": "self_evaluation",
                "evaluation": payload,
            })
        except Exception as e:
            log.warning(f"[SelfEval] 发布评估事件失败: {e}")

    def _extract_eval_summary(self, evaluation: Any) -> Dict[str, Any]:
        """从评估对象提取摘要字段，便于回填到 history 让 LLM 看到上一次评估

        ⚠️ 历史元素被 ChatResponse.history: List[Dict[str, str]] 约束，所有值必须可序列化为字符串。
        因此这里将 quality_score(float)/should_retry(bool) 转为字符串，避免 Pydantic 校验失败。
        """
        if isinstance(evaluation, dict):
            quality = evaluation.get("quality_score")
            should_retry = evaluation.get("should_retry", False)
            suggestion = evaluation.get("suggestion", "") or ""
            issues = evaluation.get("issues") or []
        else:
            quality = getattr(evaluation, "quality_score", None)
            should_retry = getattr(evaluation, "should_retry", False)
            suggestion = str(getattr(evaluation, "suggestion", "") or "")
            issues = list(getattr(evaluation, "issues", []) or [])

        # 把质量分格式化为保留 2 位小数的字符串，便于 LLM 读
        try:
            quality_str = f"{float(quality):.2f}" if quality is not None else ""
        except (TypeError, ValueError):
            quality_str = str(quality) if quality is not None else ""

        return {
            "eval_quality": quality_str,
            "eval_reason": "; ".join(str(i) for i in issues) if issues else "",
            "need_retry": "true" if should_retry else "false",
            "improvement_hint": suggestion,
        }

    def _build_self_evaluation_report(self, step_evaluations: List[Any]) -> Dict[str, Any]:
        """汇总所有步骤评估，生成整体评估报告"""
        if not step_evaluations:
            return {
                "enabled": False,
                "step_count": 0,
                "average_quality": None,
                "overall_quality": None,
                "retry_recommended": False,
                "issues_summary": [],
            }

        scores: List[float] = []
        issues_count = 0
        retry_recommended = False
        all_issues: List[str] = []

        for ev in step_evaluations:
            if isinstance(ev, dict):
                q = float(ev.get("quality_score", 0.5))
                issues = ev.get("issues") or []
                should_retry = bool(ev.get("should_retry", False))
            else:
                q = float(getattr(ev, "quality_score", 0.5))
                issues = list(getattr(ev, "issues", []) or [])
                should_retry = bool(getattr(ev, "should_retry", False))

            scores.append(q)
            if issues:
                issues_count += len(issues)
                all_issues.extend([str(i) for i in issues])
            if should_retry:
                retry_recommended = True

        avg = sum(scores) / len(scores) if scores else 0.0
        if avg >= 0.8:
            overall = "excellent"
        elif avg >= 0.6:
            overall = "good"
        elif avg >= 0.4:
            overall = "fair"
        else:
            overall = "poor"

        return {
            "enabled": True,
            "step_count": len(step_evaluations),
            "average_quality": round(avg, 3),
            "overall_quality": overall,
            "retry_recommended": retry_recommended,
            "issues_count": issues_count,
            "issues_summary": all_issues[:10],
            "step_scores": [round(s, 3) for s in scores],
        }

    def _evaluate_run_overall(
        self,
        task: str,
        history: List[Dict[str, Any]],
        step_evaluations: List[Any],
        total_iterations: int,
    ) -> Optional[Any]:
        """对整次 run 做一次运行级自评（基于 history + 步骤评估）"""
        try:
            from services.self_evaluator import StepEvaluation
        except Exception:
            return None

        # 1) 启发式信号
        avg_step_quality = 0.0
        if step_evaluations:
            qs = []
            for ev in step_evaluations:
                if isinstance(ev, dict):
                    qs.append(float(ev.get("quality_score", 0.5)))
                else:
                    qs.append(float(getattr(ev, "quality_score", 0.5)))
            avg_step_quality = sum(qs) / len(qs)

        finished_cleanly = bool(
            history and history[-1].get("action") == "FINISH"
        )
        hit_force_stop = bool(
            history and history[-1].get("action") == "FORCE_STOP"
        )

        # 3) 任务完成度（基于动作序列是否有合理推进）
        # 简单启发：FINISH + 无错误 + 平均质量 >= 0.6 → 任务完成度高
        error_keywords = ("错误", "执行失败", "不存在", "LLM调用失败")
        any_error = any(
            any(k in (s.get("observation", "") or "") for k in error_keywords)
            for s in history
        )

        # 4) 任务完成度分级
        if finished_cleanly and not any_error and avg_step_quality >= 0.6:
            completion = "high"
            composite = max(0.7, avg_step_quality)
            issues: List[str] = []
            suggestion = "整体执行良好，无明显问题。"
            should_retry = False
        elif finished_cleanly and any_error:
            completion = "medium"
            composite = min(0.6, avg_step_quality)
            issues = ["部分步骤出现错误，但最终任务完成"]
            suggestion = "可在出错步骤添加更明确的错误处理或重试"
            should_retry = False
        elif hit_force_stop:
            completion = "low"
            composite = min(0.4, avg_step_quality)
            issues = ["达到最大迭代次数未能在自然 FINISH 结束"]
            suggestion = (
                "建议提高 max_iterations 或拆分任务为更小的子目标，"
                "并允许 Agent 显式 FINISH 表达完成"
            )
            should_retry = True
        else:
            completion = "low"
            composite = min(0.4, avg_step_quality)
            issues = ["任务未能完成"]
            suggestion = "建议调整任务描述或拆解为更小步骤"
            should_retry = True

        # 4) 若有 LLM，可选：让 LLM 基于 history 给出修正建议
        llm_suggestion = ""
        try:
            if self.llm_client is not None and history:
                summary = self._summarize_history_for_llm(history)
                prompt = (
                    "你是一个 Agent 运行结果审查员。基于以下运行摘要，"
                    "指出 3 个最关键的改进建议（简洁中文 bullet 列表）。"
                    "\n\n任务：\n" + (task or "")[:500] +
                    "\n\n运行摘要：\n" + summary + "\n\n建议："
                )
                resp = self.llm_client.chat_completions(
                    model=(
                        getattr(self, "agent_model", None)
                        or os.getenv("LLM_MODEL")
                        or settings.models.agent_model
                    ),
                    messages=[
                        {"role": "system", "content": "你是严格的 Agent 审查员。"},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                    max_tokens=300,
                    stream=False,
                )
                content = (
                    resp.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                llm_suggestion = (content or "").strip()[:600]
        except Exception as e:
            log.debug(f"[SelfEval] 运行级 LLM 建议失败（非关键）: {e}")

        if llm_suggestion:
            suggestion = f"{suggestion}\nLLM 审查建议:\n{llm_suggestion}"

        return StepEvaluation(
            quality_score=max(0.0, min(1.0, composite)),
            should_retry=should_retry,
            issues=issues,
            suggestion=suggestion,
            step_index=-1,
            tool_name="__run__",
            used_llm=bool(llm_suggestion),
            # 扩展字段：保存完成度
            # 使用 suggestion/issue 之外不影响主结构
        )

    @staticmethod
    def _summarize_history_for_llm(history: List[Dict[str, Any]], max_items: int = 5) -> str:
        """把 history 压缩成简短文本供 LLM 审查"""
        lines = []
        for i, s in enumerate(history[-max_items:]):
            action = s.get("action", "")
            if len(action) > 200:
                action = action[:200] + "..."
            obs = (s.get("observation", "") or "")[:200]
            eval_q = s.get("eval_quality", "")
            lines.append(
                f"[{i}] Action: {action}\n    Obs: {obs}\n    Eval: {eval_q}"
            )
        return "\n".join(lines)
