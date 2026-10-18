import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";

const IDENTITY_OPTIONS = [
  { value: "student_junior", label: "在校低年级", group: "student" },
  { value: "student_senior", label: "高年级 / 应届", group: "student" },
  { value: "professional_1_3", label: "工作 1–3 年", group: "professional", beta: true },
  { value: "professional_more", label: "工作更久", group: "professional", beta: true },
];

export default function NewSession() {
  const [identityDetail, setIdentityDetail] = useState("student_senior");
  const [mode, setMode] = useState<"quick" | "full">("quick");
  const [goalClear, setGoalClear] = useState<boolean | null>(null);
  const [targetRole, setTargetRole] = useState("");
  const [targetCity, setTargetCity] = useState("");
  const [employmentStatus, setEmploymentStatus] = useState("");
  const [salaryFloor, setSalaryFloor] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const identity = IDENTITY_OPTIONS.find((o) => o.value === identityDetail)!.group as
    | "student"
    | "professional";

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (goalClear === null) {
      setError("请选择目标方向是否明确");
      return;
    }
    setError("");
    setBusy(true);
    try {
      const resp = await api.post<{ id: string }>("/api/sessions", {
        mode,
        identity,
        identity_detail: identityDetail,
        goal_clear: goalClear,
        target_role: goalClear ? targetRole : null,
        target_city: targetCity || null,
        employment_status: identity === "professional" ? employmentStatus || null : null,
        salary_floor: identity === "professional" ? salaryFloor || null : null,
      });
      navigate(`/chat/${resp.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "网络异常，请重试");
      setBusy(false);
    }
  }

  const card = (active: boolean) =>
    `cursor-pointer rounded-xl border p-4 text-left transition ${
      active ? "border-brand-blue bg-card" : "border-line hover:border-brand-blue/50"
    }`;

  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <Link to="/dashboard" className="text-sm text-gray-400 hover:text-navy">
        ← 返回控制台
      </Link>
      <h1 className="mt-3 text-xl font-bold text-navy">新建诊断</h1>
      <p className="mt-1 text-sm text-gray-500">
        这几项用表单收集，不占对话轮次——填完直接进入对话。
      </p>

      <form onSubmit={submit} className="mt-6 space-y-7">
        <section>
          <h2 className="text-sm font-bold text-gray-600">① 你现在的身份</h2>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {IDENTITY_OPTIONS.map((o) => (
              <button
                type="button"
                key={o.value}
                className={card(identityDetail === o.value)}
                onClick={() => setIdentityDetail(o.value)}
              >
                <span className="font-medium text-navy">{o.label}</span>
                {o.beta && (
                  <span className="ml-1 rounded bg-brand-orange px-1.5 py-0.5 text-[10px] font-bold text-white">
                    BETA
                  </span>
                )}
              </button>
            ))}
          </div>
        </section>

        <section>
          <h2 className="text-sm font-bold text-gray-600">② 诊断档位（如实告知时长）</h2>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <button type="button" className={card(mode === "quick")} onClick={() => setMode("quick")}>
              <div className="font-medium text-navy">快速档</div>
              <div className="mt-1 text-xs text-gray-500">约 15 问 / 20 分钟 · 先广后深</div>
            </button>
            <button type="button" className={card(mode === "full")} onClick={() => setMode("full")}>
              <div className="font-medium text-navy">完整档</div>
              <div className="mt-1 text-xs text-gray-500">约 30 问 / 40–60 分钟 · 逐维深挖</div>
            </button>
          </div>
        </section>

        <section>
          <h2 className="text-sm font-bold text-gray-600">③ 目标方向明确吗？</h2>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <button type="button" className={card(goalClear === true)} onClick={() => setGoalClear(true)}>
              <div className="font-medium text-navy">明确</div>
              <div className="mt-1 text-xs text-gray-500">评分将锚定你的目标岗位</div>
            </button>
            <button type="button" className={card(goalClear === false)} onClick={() => setGoalClear(false)}>
              <div className="font-medium text-navy">还没想好</div>
              <div className="mt-1 text-xs text-gray-500">走探索路径：评方向探索进度，不逼你选岗</div>
            </button>
          </div>
          {goalClear && (
            <input
              className="mt-2 w-full rounded-lg border border-line px-4 py-2.5 text-sm outline-none focus:border-brand-blue"
              placeholder="目标岗位（如：产品经理 / 商业分析 / 新媒体运营）"
              value={targetRole}
              maxLength={64}
              onChange={(e) => setTargetRole(e.target.value)}
              required
            />
          )}
          <p className="mt-2 text-xs text-gray-400">
            MVP 题库覆盖商业类岗位（商分/产品/运营/市场/管培）；技术、设计等岗位可用，但题目偏通用，岗位针对性有限。
          </p>
        </section>

        <section>
          <h2 className="text-sm font-bold text-gray-600">④ 目标城市（可选）</h2>
          <input
            className="mt-2 w-full rounded-lg border border-line px-4 py-2.5 text-sm outline-none focus:border-brand-blue"
            placeholder="如：上海 / 不限"
            value={targetCity}
            maxLength={32}
            onChange={(e) => setTargetCity(e.target.value)}
          />
        </section>

        {identity === "professional" && (
          <section>
            <h2 className="text-sm font-bold text-gray-600">⑤ 职场人补充（可跳过）</h2>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              <select
                className="rounded-lg border border-line px-4 py-2.5 text-sm outline-none focus:border-brand-blue"
                value={employmentStatus}
                onChange={(e) => setEmploymentStatus(e.target.value)}
              >
                <option value="">在职状态（可跳过）</option>
                <option value="在职">在职，偷偷看机会</option>
                <option value="已离职">已离职</option>
                <option value="即将离职">即将离职</option>
              </select>
              <input
                className="rounded-lg border border-line px-4 py-2.5 text-sm outline-none focus:border-brand-blue"
                placeholder="薪资底线（可跳过）"
                value={salaryFloor}
                maxLength={32}
                onChange={(e) => setSalaryFloor(e.target.value)}
              />
            </div>
            <p className="mt-2 text-xs text-gray-400">
              薪资底线只用于判断路径，不进对话记录、不写入报告。
            </p>
          </section>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          disabled={busy}
          className="w-full rounded-lg bg-brand-orange py-3 font-bold text-white transition hover:brightness-110 disabled:opacity-50"
        >
          {busy ? "正在创建…" : "开始对话诊断 →"}
        </button>
      </form>
    </div>
  );
}
