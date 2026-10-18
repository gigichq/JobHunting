"""报告流水线 Stage A/B/C/D 的 prompt（02-技术设计 §10，产品设计 §7）。"""
from ..interview.dimensions import DIM_BY_KEY, DIM_KEYS

_COMMON_RULES = """# 通用红线（违反即废稿）
- 不承诺 Offer、不保证结果；只说「进度低」不说「能力差」
- 不编造市场统计、薪资基准、成功率；无把握的数据标「建议自行核实」
- 薪资数字与私人敏感事（感情/健康/家庭矛盾等）一律不提取、不写入
- 禁用词：家长、学员（社招版）、同学（社招版）、最刺眼、请勿转发、仅限内部
- 全程中文，称呼用户用「你」或其称呼"""


def stage_a_prompt(transcript: str, profile: dict, identity: str) -> tuple[str, str]:
    system = f"""你是一位严谨的咨询顾问，正在从一场求职诊断访谈记录中提取事实。只提取用户确实说过的内容，绝不推断、绝不补全。

{_COMMON_RULES}

# 提取编辑规则
- 每条证据注明维度（{', '.join(DIM_KEYS)}）、来源类型（用户自述/现场展示/他人反馈转述/AI辅导后产出/AI推断）
- quote 必须是用户原话的逐字摘录（可截取片段但不得改写一个字），并给出该条用户消息的编号 message_id（方括号里 user#N 的 N）
- 数字必须带原话出处；没有原话支撑的数字不要提取
- AI 现场辅导后用户复述的答案 → source_type=AI辅导后产出
- 不确定是否说过的内容：宁可不提取"""
    user = f"""# 用户画像（表单）
身份：{identity}；目标明确：{profile.get('goal_clear')}；目标岗位：{profile.get('target_role') or '未定（探索路径）'}；城市：{profile.get('target_city') or '未填'}

# 访谈记录（[user#N] 为用户消息及其编号；[assistant#N] 为 AI 诊断师发言，不作证据）
{transcript}

请提取结构化事实，输出 JSON。"""
    return system, user


STAGE_A_SCHEMA = """{
  "profile_summary": "一段话画像（基于用户自述）",
  "timeline": "求职时间线", "weekly_hours": "每周可投入",
  "experiences": ["经历清单，每条一句话"],
  "skills": ["技能清单"],
  "job_actions": ["已发生的求职动作"],
  "key_facts": ["关键事实清单（入报告第一章）"],
  "memorable_quotes": [{"dimension": "维度key", "point": "为什么值得记住", "source_type": "用户自述", "quote": "用户原话", "message_id": 编号}],
  "evidence": [{"dimension": "维度key", "point": "证据要点一句话", "source_type": "用户自述|现场展示|他人反馈转述|AI辅导后产出|AI推断", "quote": "用户原话或null", "message_id": 编号或null}]
}"""


def stage_b_prompt(
    dim_key: str, evidence_pool: list[dict], profile: dict, identity: str
) -> tuple[str, str]:
    dim = DIM_BY_KEY[dim_key]
    goal_clear = bool(profile.get("goal_clear"))
    if goal_clear:
        anchor_ctx = f"评分锚定目标岗位「{profile.get('target_role')}」：所有证据按该岗位的要求衡量（转岗者的现有经验按目标岗位标准评）。"
    else:
        anchor_ctx = (
            "用户方向未定（探索路径）：按通用职业能力口径评分并在判断中明示此口径；"
            "若本维度是 mapping（找准岗位），评的是方向探索进度（候选方向数/比较依据/已做的市场验证），不评岗位就绪度、不下岗位匹配结论。"
        )
    translation = (
        "该用户为社招且目标明确：额外输出 translation_rows——现有经验→目标岗位转译表，"
        "每行 {current: 现有经验, target: 对目标岗位的价值, gap: 还差什么}，2–4 行，没有依据就留空数组。"
        if identity == "professional" and goal_clear
        else "translation_rows 输出空数组。"
    )
    system = f"""你是一位克制、证据导向的评估顾问，负责对「{dim['name']}」这一个维度评分。

{_COMMON_RULES}

# 评分规则
- 只依据下面给出的证据池评分：不得假设证据池之外的任何事实
- 每条判断必须在 evidence_refs 中引用证据 id；引用不存在的 id 会被系统拒绝
- 只有 source_type ∈ {{用户自述, 现场展示}} 且 status=confirmed 的证据可作计分依据；他人反馈转述仅辅助佐证；AI辅导后产出/AI推断 不可计分
- 四态证据模型：evidenced=正常评分；confirmed_absent=用户明确没做过→如实计 0–1 分（完全没有且无启动迹象=0；已有素材或具体启动计划=1）；insufficient=信息不足→score 为 null；not_applicable=不适用→score 为 null
- 整数分 0–7。评分锚点：
  0–1：{dim['anchors']['0-1']}
  2–3：{dim['anchors']['2-3']}
  4：{dim['anchors']['4']}
  5–7：{dim['anchors']['5-7']}
- {anchor_ctx}
- {translation}
- next_step 必须是本周就能开始的具体动作；deliverable_goal 是一件可交付的东西"""
    pool_lines = [
        f"- id={e['id']} status={e['status']} source={e['source_type']} point={e['point']}"
        + (f" quote=「{e['quote']}」" if e.get("quote") else "")
        for e in evidence_pool
    ]
    user = f"""# 维度：{dim['name']}（考察点：{dim['focus']}）

# 本维度证据池（Stage A′ 已校验，这是你能看到的全部信息）
{chr(10).join(pool_lines) if pool_lines else '（本维度无任何证据）'}

请评分并输出 JSON。"""
    return system, user


STAGE_B_SCHEMA = """{
  "evidence_state": "evidenced | confirmed_absent | insufficient | not_applicable",
  "score": 0到7的整数，insufficient/not_applicable 时为 null,
  "core_judgement": "核心判断一句话",
  "evidence_refs": ["引用的证据id"],
  "why": "为什么是这个分（引用证据说明，2-4 句）",
  "next_step": "下一步（本周可开始的具体动作）",
  "deliverable_goal": "近期交付目标（一件可交付的东西）",
  "translation_rows": [{"current": "...", "target": "...", "gap": "..."}]
}"""


def stage_c_prompt(
    dim_results: dict, evidence_pool: list[dict], profile: dict, identity: str, totals: dict
) -> tuple[str, str]:
    system = f"""你是一位结构化思维极强的咨询合伙人，负责从七维评分结果中提炼结构性结论。

{_COMMON_RULES}

# 结论规则
- 每条结论必须标注依赖的维度（basis_dimensions）与证据 id（evidence_refs）——依赖关系可追溯
- 允许基于证据的直接判断（如转岗 vs 换平台），但必须说明依据与置信度（高/中/低）
- 典型结构性结论示例口径：「有素材、无成品」「输入端强于输出端」
- 社招用户：输出 interview_failure_attribution——面试挂点归因，只写「可能原因＋验证办法」，绝不写成确定结论；学生用户输出空数组
- first_priority_action：当前最关键缺口＋本周优先做的一件事（选择理由/预计耗时/完成后的样子）
- 评分维度不足 4 个时（本次已评 {totals['scored_count']} 个）：conclusions 改为「已确认的发现」，不下整体判断"""
    dim_lines = [
        f"- {DIM_BY_KEY[k]['short']}({k}): state={v['evidence_state']} score={v['score']} 判断={v['core_judgement']}"
        for k, v in dim_results.items()
    ]
    pool_lines = [
        f"- id={e['id']} dim={e['dimension']} point={e['point']}" for e in evidence_pool
    ]
    user = f"""# 用户
身份：{identity}；目标明确：{profile.get('goal_clear')}；目标岗位：{profile.get('target_role') or '探索中'}

# 七维评分结果（总分 {totals['total']}/{totals['max']}·已评 {totals['scored_count']} 维）
{chr(10).join(dim_lines)}

# 证据池索引
{chr(10).join(pool_lines)}

请输出结构性结论 JSON。"""
    return system, user


STAGE_C_SCHEMA = """{
  "one_liner": "一句话总结",
  "keywords": ["三个关键词"],
  "io_interpretation": "输入端（维1-4）/输出端（维5-7）结构解读，2-4 句",
  "conclusion_tags": ["结论标签，如 有素材无成品"],
  "conclusions": [{"text": "结论", "basis_dimensions": ["维度key"], "evidence_refs": ["证据id"], "confidence": "高|中|低"}],
  "constraints": [{"constraint": "现实约束", "counter": "对策"}],
  "interview_failure_attribution": [{"possible_cause": "可能原因", "verify_method": "验证办法"}],
  "first_priority_action": {"gap": "最关键缺口", "action": "本周优先做的一件事", "reason": "选择理由", "time_cost": "预计耗时", "sample": "完成后的样子"}
}"""


def _narrative_system(identity: str, display_name: str) -> str:
    tone = (
        "读者是在校/应届学生，语气像一位真诚的学长学姐＋专业顾问"
        if identity == "student"
        else "读者是工作 1–3 年的职场人，语气像一位平视的资深同行，禁用学生场景词汇（学员/同学/在校/课程/社团）"
    )
    return f"""你是「求职陪跑」的首席报告撰写人，文风：克制、具体、温度在细节里，不打鸡血不说教。{tone}。称呼用户为「{display_name}」或「你」。

{_COMMON_RULES}

# 叙事规则
- 每个论断都要能追溯到给你的事实；不新增事实、不夸大
- 固定话术库可自然引用：分数低是进度低，不是能力低／低分不是警报，而是地图／分数是截距，潜力是斜率／很多方向不是想出来的，是做出来的
- 禁用打击性措辞：用「还没开始做」语系
- 行动建议全部为自助动作＋AI 陪跑，不得出现买课/付费解锁"""


def stage_d1_prompt(context: str, identity: str, display_name: str) -> tuple[str, str]:
    return (
        _narrative_system(identity, display_name),
        f"""{context}

请撰写报告的叙事部分①（执行摘要/快照/亮点），输出 JSON。
- exec_summary：速读版开头的一段话总结（3-5 句）
- strengths：优势牌 ≤4 张，每张 {{title: 短标题, detail: 2-3 句，引证据}}——这是用户最先看到且唯一愿意分享的部分，必须真实且提气
- to_fill：待补齐清单（不打击，用「还没开始做」语系）
- snapshot.rows：背景快照表 [{{label, value}}]（{'学员快照' if identity == 'student' else '职业履历卡'}）
- highlights：亮点与潜力 ≤6 项不计分（「分数是截距，潜力是斜率」）
- environment_observation：环境观察（基于用户所述的时间线/约束，没有信息就留空字符串）""",
    )


STAGE_D1_SCHEMA = """{
  "exec_summary": "...",
  "strengths": [{"title": "...", "detail": "..."}],
  "to_fill": ["..."], "potential_direction": "...", "one_sentence_for_you": "...",
  "snapshot": {"rows": [{"label": "...", "value": "..."}]},
  "environment_observation": "...",
  "highlights": [{"title": "...", "detail": "..."}]
}"""


def stage_d2_prompt(context: str, identity: str, display_name: str) -> tuple[str, str]:
    week_label = "两周面试应急包（3 个动作）" if identity == "professional" else "本周 3 个动作"
    return (
        _narrative_system(identity, display_name),
        f"""{context}

请撰写报告的叙事部分②（行动计划/执行机制/结语），输出 JSON。
- week_actions：{week_label}，每个 {{action: 动作, why: 为什么是它, deliverable_template: 直接可用的交付物模板——STAR 模板已填好该用户的素材骨架 / JD 三栏表 / 可复制的 AI prompt，三选一，要能直接复制使用}}
- ninety_day_plan：90 天补底子，按阶段 [{{phase: 如 第1-4周, focus: 主攻, actions: [动作]}}]
- weekly_rhythm：每周节奏建议（2-3 句）
- kanban_checklist：求职看板清单（5-8 项可勾选）
- retest_advice：复测建议（何时回来复测哪些维度；不推销任何东西）
- ending_letter：「致{display_name}」结语正文（3-5 段，真诚、具体、落在行动上，引用至少一句用户原话须来自已验证引语）""",
    )


STAGE_D2_SCHEMA = """{
  "week_actions": [{"action": "...", "why": "...", "deliverable_template": "..."}],
  "ninety_day_plan": [{"phase": "...", "focus": "...", "actions": ["..."]}],
  "weekly_rhythm": "...", "kanban_checklist": ["..."], "retest_advice": "...",
  "ending_letter": "..."
}"""
