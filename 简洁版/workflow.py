from __future__ import annotations

from typing import Any

from utils import answer_to_display, answer_to_display_verbose, normalize_answer, normalize_text, fuzzy_score
from config import ANSWER_INTERVAL_MS

LOOP_MAX_COUNT = 9999  # 最大循环次数


def run_record_once(dom_service, db, log, threshold: float = 0.82) -> dict[str, Any]:
    """录制题目一次"""
    try:
        data = dom_service.extract_question_data()
        question_type = data["question_type"]
        question_text = data["question_text"]
        options = data["options"]
        log(f"题目: {question_text}")
        matched = db.find_question(question_text, options, threshold=threshold)
        is_multi_choice = "多选" in str(question_type or "")

        if matched:
            old_answer_raw = matched.get("answer", "") or ""
            old_answer = normalize_answer(old_answer_raw)
            question_id = matched.get("id", "未知")
            if not is_multi_choice:
                answer = answer_to_display_verbose(old_answer)
                log(f"题库命中(ID={question_id})，答案: {answer}")
                next_ok = dom_service.click_next_question()
                return {
                    "ok": True,
                    "mode": "record",
                    "source": "db",
                    "question": question_text,
                    "question_type": question_type,
                    "options": options,
                    "answer": answer,
                    "analysis": matched.get("analysis", "") or "",
                    "status": "题库已存在，已自动翻题" if next_ok else "题库已存在，翻题失败",
                }

            log(f"多选题命中(ID={question_id})旧记录，准备重新校正")
            log(f"原旧答案: {answer_to_display_verbose(old_answer)}")
            expanded = dom_service.expand_answer_explanation()
            if not expanded:
                log("多选题命中，但解析提取失败，保留原答案")
                next_ok = dom_service.click_next_question()
                return {
                    "ok": True,
                    "mode": "record",
                    "source": "db",
                    "question": question_text,
                    "question_type": question_type,
                    "options": options,
                    "answer": answer_to_display_verbose(old_answer),
                    "analysis": matched.get("analysis", "") or "",
                    "status": "多选题命中，解析展开失败，已保留原答案" + ("，已自动翻题" if next_ok else "，翻题失败"),
                }

            new_answer_raw, new_analysis = dom_service.extract_correct_answer_from_explanation(question_type, options)
            new_answer = new_answer_raw
            if not new_answer:
                log("多选题命中，但解析提取失败，保留原答案")
                next_ok = dom_service.click_next_question()
                return {
                    "ok": True,
                    "mode": "record",
                    "source": "db",
                    "question": question_text,
                    "question_type": question_type,
                    "options": options,
                    "answer": answer_to_display_verbose(old_answer),
                    "analysis": matched.get("analysis", "") or "",
                    "status": "多选题命中，解析提取失败，已保留原答案" + ("，已自动翻题" if next_ok else "，翻题失败"),
                }

            log(f"新解析答案: {answer_to_display_verbose(new_answer)}")
            if new_answer == old_answer:
                log("多选题命中，最新解析与库中一致，跳过更新")
                next_ok = dom_service.click_next_question()
                return {
                    "ok": True,
                    "mode": "record",
                    "source": "db",
                    "question": question_text,
                    "question_type": question_type,
                    "options": options,
                    "answer": answer_to_display_verbose(old_answer),
                    "analysis": new_analysis or matched.get("analysis", "") or "",
                    "status": "多选题命中，无需更新" + ("，已自动翻题" if next_ok else "，翻题失败"),
                }

            # 验证匹配到的题目是否真的匹配
            match_score = matched.get("_match_score", 1.0)
            from utils import normalize_text, fuzzy_score
            if match_score < 0.90:
                # 匹配置信度不够，检查题目文本是否真的相似
                old_text_norm = normalize_text(matched.get("question_text", "") or "")
                new_text_norm = normalize_text(question_text)
                text_similarity = fuzzy_score(old_text_norm, new_text_norm)
                log(f"多选题命中，匹配置信度={match_score:.2f}，文本相似度={text_similarity:.2f}")
                if text_similarity < 0.90:
                    # 文本相似度不够，可能是不同题目
                    log("匹配题目与当前题目相似度不足，插入新记录而非更新")
                    inserted, row_id = db.insert_question_if_not_exists(
                        question_type=question_type or "多选题",
                        question_text=question_text,
                        options=options,
                        answer=new_answer,
                        analysis=new_analysis or "",
                        source="web_dom_自动录题(新)"
                    )
                    next_ok = dom_service.click_next_question()
                    return {
                        "ok": True,
                        "mode": "record",
                        "source": "record_new",
                        "question": question_text,
                        "question_type": question_type,
                        "options": options,
                        "answer": answer_to_display_verbose(new_answer),
                        "analysis": new_analysis or "",
                        "status": f"插入新记录(ID={row_id})" + ("，已自动翻题" if next_ok else "，翻题失败"),
                    }

            updated = db.update_question_answer(int(matched["id"]), new_answer, new_analysis or matched.get("analysis", "") or "")
            if updated:
                log(f"已覆盖旧答案: {answer_to_display_verbose(old_answer)} -> {answer_to_display_verbose(new_answer)}")
            else:
                log("多选题命中，但数据库更新失败，保留原答案")
                new_answer = old_answer
            next_ok = dom_service.click_next_question()
            return {
                "ok": True,
                "mode": "record",
                "source": "db_overwrite" if updated else "db",
                "question": question_text,
                "question_type": question_type,
                "options": options,
                "answer": answer_to_display_verbose(new_answer),
                "analysis": new_analysis or matched.get("analysis", "") or "",
                "status": ("多选题旧答案已覆盖" if updated else "多选题命中，保留原答案") + ("，已自动翻题" if next_ok else "，翻题失败"),
            }

        log("题库未命中，尝试展开答案解析")
        expanded = dom_service.expand_answer_explanation()
        if not expanded:
            return {
                "ok": False,
                "mode": "record",
                "source": "record",
                "question": question_text,
                "question_type": question_type,
                "options": options,
                "answer": "",
                "analysis": "",
                "status": "解析展开失败",
            }

        answer, analysis = dom_service.extract_correct_answer_from_explanation(question_type, options)
        if not answer:
            log("解析区未提取到有效答案")
            return {
                "ok": False,
                "mode": "record",
                "source": "record",
                "question": question_text,
                "question_type": question_type,
                "options": options,
                "answer": "",
                "analysis": analysis,
                "status": "未提取到答案",
            }

        inserted, row_id = db.insert_question_if_not_exists(
            question_type=question_type or "单选题",
            question_text=question_text,
            options=options,
            answer=answer,
            analysis=analysis,
            source="web_dom_自动录题",
        )
        log(f"录题成功，ID={row_id}" if inserted else f"题目已存在，ID={row_id}")
        next_ok = dom_service.click_next_question()
        return {
            "ok": True,
            "mode": "record",
            "source": "record",
            "question": question_text,
            "question_type": question_type,
            "options": options,
            "answer": answer_to_display_verbose(answer),
            "analysis": analysis,
            "status": ("录题成功" if inserted else "题目已存在") + ("，已自动翻题" if next_ok else "，翻题失败"),
        }
    except Exception as exc:
        log(f"录题模式异常: {exc}")
        return {"ok": False, "mode": "record", "status": f"录题异常: {exc}", "question": "", "answer": "", "options": []}


def run_assist_once(dom_service, db, log, threshold: float = 0.82, enable_supplement_on_miss: bool = True) -> dict[str, Any]:
    """辅助答题一次"""
    try:
        data = dom_service.extract_question_data()
        question_type = data["question_type"]
        question_text = data["question_text"]
        options = data["options"]
        log(f"题目: {question_text}")
        matched = db.find_question(question_text, options, threshold=threshold)
        if matched:
            raw_answer = matched.get("answer", "") or ""
            answer = answer_to_display_verbose(raw_answer)
            question_id = matched.get("id", "未知")
            log(f"题库命中(ID={question_id})，答案: {answer}")
            return {
                "ok": True,
                "mode": "assist",
                "source": "db",
                "question": question_text,
                "question_type": question_type,
                "options": options,
                "answer": answer,
                "answer_raw": raw_answer,  # 原始复合格式，用于精准点击
                "analysis": matched.get("analysis", "") or "",
                "status": "题库命中",
            }

        log("题库未命中")
        if not enable_supplement_on_miss:
            return {
                "ok": False,
                "mode": "assist",
                "source": "none",
                "question": question_text,
                "question_type": question_type,
                "options": options,
                "answer": "",
                "analysis": "",
                "status": "题库未命中",
            }

        log("未命中，尝试展开答案解析补录")
        expanded = dom_service.expand_answer_explanation()
        if not expanded:
            log("未命中，解析展开失败")
            return {
                "ok": False,
                "mode": "assist",
                "source": "miss",
                "question": question_text,
                "question_type": question_type,
                "options": options,
                "answer": "",
                "analysis": "",
                "status": "未命中，解析展开失败",
            }

        answer, analysis = dom_service.extract_correct_answer_from_explanation(question_type, options)
        if not answer:
            log("未命中，解析答案提取失败")
            return {
                "ok": False,
                "mode": "assist",
                "source": "miss",
                "question": question_text,
                "question_type": question_type,
                "options": options,
                "answer": "",
                "analysis": analysis,
                "status": "未命中，解析答案提取失败",
            }

        inserted, row_id = db.insert_question_if_not_exists(
            question_type=question_type or "单选题",
            question_text=question_text,
            options=options,
            answer=answer,
            analysis=analysis,
            source="web_dom_辅助答题补录",
        )
        log(f"未命中，已补录到题库，ID={row_id}" if inserted else f"未命中，题目已存在，ID={row_id}")
        return {
            "ok": True,
            "mode": "assist",
            "source": "supplement",
            "question": question_text,
            "question_type": question_type,
            "options": options,
            "answer": answer_to_display_verbose(answer),
            "answer_raw": answer,  # 原始复合格式
            "analysis": analysis,
            "status": "未命中，已补录到题库" if inserted else "未命中，题目已存在",
            "supplemented": inserted,
        }
    except Exception as exc:
        log(f"辅助答题模式异常: {exc}")
        return {"ok": False, "mode": "assist", "status": f"辅助答题异常: {exc}", "question": "", "answer": "", "options": []}


def run_auto_answer_cycle(dom_service, db, log, cycle_count: int = 1, threshold: float = 0.82,
                           question_bank: int = 1, username: str = "", password: str = "",
                           stop_event=None, answer_delay: int = 1500) -> dict[str, Any]:
    """
    全自动答题循环
    完整流程: 登录 → 点击进入 → 选择题库 → 继续考试 → 开始考试 → 逐题作答(查答案→点选项→下一题) → 交卷 → 再考一次 → 循环
    """
    def _check_stop():
        """检查停止事件，如果被停止则返回True"""
        if stop_event and stop_event.is_set():
            log("收到停止信号，正在停止答题...")
            return True
        return False

    log(f"开始全自动答题，轮数: {'无限' if cycle_count == 0 else cycle_count}，题库: {question_bank}")
    total_answered = 0
    total_failed = 0
    current_cycle = 0
    _restart_flow = False  # 标记是否需要重新执行进入/选择题库
    _restart_attempts = 0  # 重启尝试次数上限

    while True:
        # 检查停止事件
        if _check_stop():
            break

        # 检查是否完成所有轮数
        if cycle_count > 0 and current_cycle >= cycle_count:
            log(f"已完成 {cycle_count} 轮答题")
            break

        current_cycle += 1
        log(f"=== 第 {current_cycle}/{cycle_count if cycle_count > 0 else '无限'} 轮 ===")

        page = dom_service.ensure_page()
        # 等待页面渲染稳定（老旧电脑需要更长时间）
        dom_service.wait_for_page_stable(timeout=10000)

        # 步骤1: 点击"进入"按钮（第一轮或检测到需要重新进入时）
        if current_cycle == 1 or _restart_flow:
            log("步骤1: 点击'进入'按钮...")
            if not dom_service.click_enter_button():
                log("未找到'进入'按钮，可能已在考试区域")
            if _check_stop():
                break
            page.wait_for_timeout(3000)

        # 步骤2: 选择题库（第一轮或重启时）
        if current_cycle == 1 or _restart_flow:
            if _check_stop():
                break
            log(f"步骤2: 选择题库 {question_bank}...")
            if not dom_service.select_question_bank(question_bank):
                log(f"选择题库 {question_bank} 失败")
            page.wait_for_timeout(2000)
            _restart_flow = False  # 进入/选库执行完毕后清除重启标记

        # 步骤3: 点击"继续考试"或"重新考试"
        if _check_stop():
            break
        log("步骤3: 点击'继续考试'...")
        if not dom_service.click_continue_exam():
            log("未找到'继续考试'或'重新考试'按钮，可能已在考试准备页")
        page.wait_for_timeout(5000)

        # 步骤4: 点击"开始考试"
        if _check_stop():
            break
        log("步骤4: 点击'开始考试'...")
        if not dom_service.click_start_exam():
            log("未找到'开始考试'按钮，尝试继续答题")
        page.wait_for_timeout(3000)

        # 确保已进入答题页面
        if _check_stop():
            break
        max_wait = 10
        for _ in range(max_wait):
            if _check_stop():
                break
            if dom_service.is_exam_page():
                log("已确认进入答题页面")
                break
            page.wait_for_timeout(1000)
        else:
            log("等待答题页面超时，尝试返回自主练测重试...")
            # 返回上一页并重试进入流程
            _restart_flow = True
            _restart_attempts += 1
            if _restart_attempts > 3:
                log("重试次数过多，放弃此次答题")
                break
            try:
                page.go_back(timeout=5000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            continue  # 回到循环头部重新执行步骤1-4

        # 步骤5: 逐题答题循环
        log("步骤5: 开始逐题答题...")
        question_num = 0
        while True:
            try:  # 单题异常保护：防止一题出错导致整轮崩溃
                # 检查停止事件
                if _check_stop():
                    break

                question_num += 1
                log(f"第 {question_num} 题...")

                # 检查是否意外进入了结果页
                if dom_service.is_result_page():
                    log("检测到结果页面，跳出答题循环")
                    break

                # 调用 run_assist_once 获取答案（含自动补录）
                result = run_assist_once(dom_service, db, log, threshold=threshold, enable_supplement_on_miss=True)

                answer = result.get("answer", "")
                # answer_raw 是原始复合格式（字母|||文字），用于精准文字匹配点击
                answer_raw = result.get("answer_raw", "") or answer
                options = result.get("options", [])
                question_text = result.get("question", "")

                if not result.get("ok") or not answer:
                    log(f"获取答案失败: {result.get('status', '')}")
                    total_failed += 1
                    # 跳过此题：点第一个选项然后下一题
                    if options:
                        dom_service._click_option_by_index(0)
                        log("无答案，已点击第一个选项（跳过）")
                    next_result = dom_service.click_next_question()
                    if next_result == "submit":
                        # 防漏题检测：确认没有未答题再交卷
                        if dom_service.has_unanswered_question():
                            log("还有未答题目，不交卷，继续答题")
                            page.wait_for_timeout(2000)
                            continue
                        log("已点击'我要交卷'，等待确认对话框...")
                        if _check_stop():
                            break
                        page.wait_for_timeout(2000)
                        # 点击确认对话框中的"交卷"按钮
                        submit_ok = dom_service.click_submit_exam()
                        if submit_ok is True:
                            log("已确认交卷")
                        elif submit_ok == "unanswered":
                            # 答题卡模式：逐题补答未做题
                            log("检测到未作答提示，进入答题卡补答模式")
                            page.wait_for_timeout(1000)
                            if dom_service.click_answer_card_tab():
                                unanswered_nums = dom_service.get_unanswered_numbers_from_card()
                                if unanswered_nums:
                                    for qnum in unanswered_nums:
                                        if _check_stop():
                                            break
                                        dom_service.goto_question_by_number(qnum)
                                        page.wait_for_timeout(2000)
                                        # 获取答案并答题
                                        card_result = run_assist_once(dom_service, db, log, threshold=threshold, enable_supplement_on_miss=True)
                                        card_answer = card_result.get("answer", "")
                                        card_raw = card_result.get("answer_raw", "") or card_answer
                                        card_opts = card_result.get("options", [])
                                        if card_answer:
                                            for rt in range(3):
                                                if dom_service.click_option_by_text(card_raw, card_opts):
                                                    log(f"答题卡补第{qnum}题已点击答案: {card_answer}")
                                                    total_answered += 1
                                                    break
                                                page.wait_for_timeout(500)
                                            else:
                                                log(f"答题卡补第{qnum}题失败")
                                                total_failed += 1
                                        page.wait_for_timeout(1500)
                                    # 全部补答完，从答题卡交卷
                                    dom_service.click_submit_from_card()
                                    page.wait_for_timeout(2000)
                                    # 检查是否还有未答对话框
                                    final_check = dom_service.click_submit_exam()
                                    if final_check is True:
                                        log("补答后已确认交卷")
                                        break
                                    elif final_check == "unanswered":
                                        log("补答后仍有未做题，继续答题")
                                        continue
                                    # 如果对话框已不存在，说明已成功交卷
                                    log("补答后交卷完成")
                                    break
                            # 答题卡处理失败，回去继续
                            continue
                        elif submit_ok is False:
                            log("弹窗提示有未做题，取消交卷继续答题")
                            page.wait_for_timeout(1000)
                            continue  # 回去继续答题
                        else:
                            log("未找到确认对话框，继续执行")
                        page.wait_for_timeout(3000)
                        break
                    elif next_result == "":
                        log("未找到'下一题'或'我要交卷'，跳出")
                        break
                    continue

                # 点击答案选项（重试 3 次）
                success = False
                for retry in range(3):
                    success = dom_service.click_option_by_text(answer_raw, options)
                    if success:
                        break
                    log(f"点击答案重试 ({retry+1}/3)...")
                    page.wait_for_timeout(500)
                if success:
                    log(f"已点击答案: {answer}")
                    total_answered += 1
                else:
                    log(f"点击答案失败: {answer}")
                    total_failed += 1

                # 点击"下一题"或"我要交卷"
                next_result = dom_service.click_next_question()
                if next_result == "submit":
                    # 防漏题检测：确认没有未答题再交卷
                    if dom_service.has_unanswered_question():
                        log("还有未答题目，不交卷，继续答题")
                        page.wait_for_timeout(2000)
                        continue
                    log("已点击'我要交卷'，等待确认对话框...")
                    if _check_stop():
                        break
                    page.wait_for_timeout(2000)
                    # 点击确认对话框中的"交卷"按钮
                    submit_ok = dom_service.click_submit_exam()
                    if submit_ok is True:
                        log("已确认交卷")
                    elif submit_ok == "unanswered":
                        log("检测到未作答提示，进入答题卡补答模式")
                        page.wait_for_timeout(1000)
                        if dom_service.click_answer_card_tab():
                            unanswered_nums = dom_service.get_unanswered_numbers_from_card()
                            if unanswered_nums:
                                for qnum in unanswered_nums:
                                    if _check_stop():
                                        break
                                    dom_service.goto_question_by_number(qnum)
                                    page.wait_for_timeout(2000)
                                    card_result = run_assist_once(dom_service, db, log, threshold=threshold, enable_supplement_on_miss=True)
                                    card_answer = card_result.get("answer", "")
                                    card_raw = card_result.get("answer_raw", "") or card_answer
                                    card_opts = card_result.get("options", [])
                                    if card_answer:
                                        for rt in range(3):
                                            if dom_service.click_option_by_text(card_raw, card_opts):
                                                log(f"答题卡补第{qnum}题已点击答案: {card_answer}")
                                                total_answered += 1
                                                break
                                            page.wait_for_timeout(500)
                                        else:
                                            log(f"答题卡补第{qnum}题失败")
                                            total_failed += 1
                                    page.wait_for_timeout(1500)
                                dom_service.click_submit_from_card()
                                page.wait_for_timeout(2000)
                                final_check = dom_service.click_submit_exam()
                                if final_check is True:
                                    log("补答后已确认交卷")
                                    break
                                elif final_check == "unanswered":
                                    log("补答后仍有未做题，继续答题")
                                    continue
                                log("补答后交卷完成")
                                break
                        continue
                    elif submit_ok is False:
                        log("弹窗提示有未做题，取消交卷继续答题")
                        page.wait_for_timeout(1000)
                        continue
                    else:
                        log("未找到确认对话框，继续执行")
                    page.wait_for_timeout(3000)
                    break
                elif next_result == "":
                    log("未找到'下一题'或'我要交卷'按钮，跳出")
                    break

                page.wait_for_timeout(answer_delay)

            except Exception as e:
                log(f"第 {question_num} 题执行异常: {e}，跳过此题继续")
                total_failed += 1
                try:
                    r = dom_service.click_next_question()
                except Exception:
                    log("跳过题目时点击下一题也失败，退出答题循环")
                    break
                continue

        # 步骤6: 等待结果页面，点击"再考一次"
        log("步骤6: 等待结果页面...")
        if _check_stop():
            break
        page.wait_for_timeout(5000)  # 增加等待时间，给页面更多加载时间

        # 确认是否在结果页面（增加重试次数和等待时间）
        result_wait_count = 0
        max_wait_count = 15  # 从10增加到15
        while not dom_service.is_result_page() and result_wait_count < max_wait_count:
            result_wait_count += 1
            log(f"等待结果页面 {result_wait_count}/{max_wait_count}...")
            if _check_stop():
                break
            # 如果等待超过5次还没检测到，尝试刷新页面
            if result_wait_count == 5:
                log("等待时间较长，尝试刷新页面...")
                try:
                    page.reload(timeout=10000)
                    page.wait_for_timeout(3000)
                except:
                    pass
            page.wait_for_timeout(3000)  # 从2秒增加到3秒

        if not dom_service.is_result_page():
            log("未检测到结果页面，可能交卷失败，尝试重新进入考试流程...")
            # 不直接结束，而是尝试重新进入流程
            if _restart_attempts >= 3:
                log(f"已尝试 {_restart_attempts} 次重启均失败，答题结束")
                break
            _restart_attempts += 1
            _restart_flow = True
            current_cycle -= 1  # 不退轮数，重新执行这一轮
            continue

        # 检测考试分数
        score = dom_service.get_exam_score()
        log(f"考试分数: {score}")
        
        # 分数 ≤ 98.5 时自动回顾错题并补录（移动端视图下已修复卡住问题）
        if score <= 98.5:
            if _check_stop():
                break
            log("分数不超过98.5，自动回顾本次答题过程...")
            page.wait_for_timeout(2000)
            try:
                if dom_service.click_exam_review():
                    page.wait_for_timeout(3000)
                    if _check_stop():
                        break
                    updated = dom_service.get_wrong_questions_from_review(db, log, threshold=threshold)
                    log(f"已从考试回顾更新 {updated} 道错题")
                    page.wait_for_timeout(2000)
                    page.go_back()
                    page.wait_for_timeout(3000)
                else:
                    log("未找到'回顾本次答题过程'按钮，跳过回顾")
            except Exception as e:
                log(f"考试回顾过程异常: {e}，跳过回顾直接进入下一轮")
                try:
                    page.go_back()
                except Exception:
                    pass
                page.wait_for_timeout(2000)
        
        # 点击"再考一次"（如找不到会自动尝试"重新考试"）
        if _check_stop():
            break
        retry_count = 0
        retry_success = False
        while retry_count < 3:
            if _check_stop():
                break
            if dom_service.click_retry_button():
                log("已点击重试按钮，准备下一轮")
                retry_success = True
                page.wait_for_timeout(3000)
                # 等待页面加载完成
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)
                break
            retry_count += 1
            log(f"点击重试按钮失败 {retry_count}/3...")
            page.wait_for_timeout(2000)

        if not retry_success:
            if _restart_attempts >= 3:
                log(f"已尝试 {_restart_attempts} 次重启均失败，答题结束")
                break
            _restart_attempts += 1
            log(f"未找到'再考一次'按钮，尝试重新进入考试流程（第 {_restart_attempts} 次）...")
            _restart_flow = True
            current_cycle -= 1  # 不退轮次，重新执行这一轮
            continue

    log(f"答题完成！总共答题: {total_answered}，失败: {total_failed}")
    return {
        "ok": True,
        "mode": "auto_answer",
        "total_answered": total_answered,
        "total_failed": total_failed,
        "status": f"答题完成！成功: {total_answered}，失败: {total_failed}",
    }


def run_question_bank_check(dom_service, db, log, threshold: float = 0.82) -> dict[str, Any]:
    """
    自动跑一遍题库：用题库中的所有题目测试答题功能
    """
    log("开始自动跑题库...")
    questions = db.get_all_questions()
    if not questions:
        log("题库为空！")
        return {"ok": False, "status": "题库为空"}

    log(f"题库共有 {len(questions)} 道题目")
    success_count = 0
    fail_count = 0

    for i, q in enumerate(questions):
        log(f"[{i+1}/{len(questions)}] 检查题目: {q['question_text'][:50]}...")
        # 这里可以添加实际的答题验证逻辑
        # 目前只是统计
        if q.get("answer"):
            success_count += 1
        else:
            fail_count += 1

    log(f"题库检查完成！有答案: {success_count}，无答案: {fail_count}")
    return {
        "ok": True,
        "mode": "bank_check",
        "total": len(questions),
        "with_answer": success_count,
        "without_answer": fail_count,
        "status": f"题库检查完成！有答案: {success_count}，无答案: {fail_count}",
    }


def run_exam_review_manual(dom_service, db, log, threshold: float = 0.82) -> dict[str, Any]:
    """
    手动触发'回顾本次答题过程'：在结果页面点击回顾按钮，记录错题后返回
    用户在答题完成后，可以手动点击此按钮来补录错题
    """
    log("开始手动考试回顾...")
    try:
        page = dom_service.ensure_page()
        if not dom_service.click_exam_review():
            log("未找到'回顾本次答题过程'按钮，请确认当前在考试结果页面")
            return {"ok": False, "status": "未找到回顾按钮，请确认当前在考试结果页面"}

        page.wait_for_timeout(3000)

        # 获取错题并存入数据库
        updated = dom_service.get_wrong_questions_from_review(db, log, threshold=threshold)
        log(f"考试回顾完成，已更新 {updated} 道错题")

        page.wait_for_timeout(2000)
        # 返回结果页面
        page.go_back()
        page.wait_for_timeout(3000)

        return {
            "ok": True,
            "mode": "exam_review",
            "updated": updated,
            "status": f"考试回顾完成，已更新 {updated} 道错题",
        }
    except Exception as e:
        log(f"考试回顾异常: {e}")
        try:
            dom_service.ensure_page().go_back()
        except Exception:
            pass
        return {"ok": False, "status": f"考试回顾异常: {e}"}
